# bot.py

import discord
from discord.ext import commands, tasks
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from firebase_admin import credentials, firestore, initialize_app
import os
from datetime import datetime, date, timezone
import logging
from typing import Optional, List, Dict, Any
import shutil
import json
import platform
import sys
from webdriver_manager.core.os_manager import OperationSystemManager, ChromeType
from webdriver_manager.core.download_manager import DownloadManager
from webdriver_manager.core.driver_cache import DriverCacheManager
from webdriver_manager.core.file_manager import File
from webdriver_manager.core.driver import Driver

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Firebase Setup ---
# It's recommended to load credentials from an environment variable or a secure path
# For local development, you might place your service account key file in the same directory
# and set the environment variable FIREBASE_CREDENTIALS_PATH
FIREBASE_CREDENTIALS_PATH = os.environ.get('FIREBASE_CREDENTIALS_PATH', 'firebase_credentials.json')

try:
    if os.path.exists(FIREBASE_CREDENTIALS_PATH):
        cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
        initialize_app(cred)
        db = firestore.client()
        logging.info("Firebase successfully initialized.")
    else:
        logging.error(f"Firebase credentials file not found at {FIREBASE_CREDENTIALS_PATH}. "
                      "Please set FIREBASE_CREDENTIALS_PATH environment variable or place the file.")
        exit()
except Exception as e:
    logging.error(f"Error initializing Firebase: {e}")
    exit()

# Attempt to clear webdriver-manager cache once on startup
logging.info("Attempting one-time webdriver-manager cache clear on startup...")
try:
    wdm_cache_root = os.path.expanduser("~/.wdm")
    drivers_json_path = os.path.join(wdm_cache_root, "drivers.json")
    drivers_dir_path = os.path.join(wdm_cache_root, "drivers")

    if os.path.exists(drivers_json_path):
        os.remove(drivers_json_path)
        logging.info(f"Removed webdriver-manager cache file: {drivers_json_path}")
    else:
        logging.info(f"webdriver-manager cache file not found, no need to remove: {drivers_json_path}")

    if os.path.exists(drivers_dir_path):
        shutil.rmtree(drivers_dir_path)
        logging.info(f"Removed webdriver-manager cache directory: {drivers_dir_path}")
    else:
        logging.info(f"webdriver-manager cache directory not found, no need to remove: {drivers_dir_path}")
    logging.info("Finished one-time webdriver-manager cache clear attempt.")
except Exception as e:
    logging.error(f"Error during one-time webdriver-manager cache clear: {e}")

# --- Custom WebDriver Manager components to fix binary identification ---
class CustomDriverCacheManager(DriverCacheManager):
    def _find_correct_binary(self, files_in_archive: List[str], driver_name: str) -> str:
        """Helper to find the correct binary name/path from the list of files in an archive."""
        logging.debug(f"[CustomDriverCacheManager._find_correct_binary] Finding binary for '{driver_name}' in {files_in_archive}")
        
        normalized_driver_name = driver_name.lower()
        expected_exe_filename = f"{normalized_driver_name}.exe"
        expected_non_exe_filename = normalized_driver_name

        candidate_binaries = []
        for path_in_archive in files_in_archive:
            filename_only = os.path.basename(path_in_archive).lower()
            if platform.system() == "Windows":
                if filename_only == expected_exe_filename:
                    candidate_binaries.append(path_in_archive)
            else: # Linux, macOS
                if filename_only == expected_non_exe_filename and not path_in_archive.lower().endswith(".exe"):
                    candidate_binaries.append(path_in_archive)
        
        if candidate_binaries:
            if len(candidate_binaries) > 1:
                # Prefer candidates in a subdirectory that often matches part of the driver/os name, e.g., "chromedriver-win64/chromedriver.exe"
                for cb in candidate_binaries:
                    path_parts = os.path.normpath(cb).split(os.sep)
                    if len(path_parts) > 1 and (normalized_driver_name in path_parts[0].lower() or self.get_os_type() in path_parts[0].lower()):
                        logging.info(f"[CustomDriverCacheManager._find_correct_binary] Selected nested candidate: '{cb}'")
                        return cb
                logging.info(f"[CustomDriverCacheManager._find_correct_binary] Multiple direct candidates, selected first: '{candidate_binaries[0]}'")
                return candidate_binaries[0]
            logging.info(f"[CustomDriverCacheManager._find_correct_binary] Single direct candidate found: '{candidate_binaries[0]}'")
            return candidate_binaries[0]

        logging.warning(f"[CustomDriverCacheManager._find_correct_binary] No direct executable match for '{driver_name}'. Trying broader fallback.")
        for path_in_archive in files_in_archive:
            name_lower = path_in_archive.lower()
            if 'notice' in name_lower or 'license' in name_lower or name_lower.endswith(('.txt', '.xml', '.json', '.md', '.pdf', '.html')):
                continue
            file_basename_no_ext = os.path.splitext(os.path.basename(name_lower))[0]
            if normalized_driver_name in file_basename_no_ext:
                logging.info(f"[CustomDriverCacheManager._find_correct_binary] Fallback found potential binary: '{path_in_archive}'")
                return path_in_archive

        raise Exception(f"[CustomDriverCacheManager._find_correct_binary] Cannot find binary for '{driver_name}'. Files in archive: {files_in_archive}")

    def save_file_to_cache(self, driver: Driver, file_obj: File) -> str:
        """Overrides DriverCacheManager.save_file_to_cache to use custom binary finding logic."""
        logging.debug(f"[CustomDriverCacheManager.save_file_to_cache] Saving driver '{driver.get_name()}' version '{driver.get_driver_version_to_download()}'")
        
        # Determine the path where the driver archive will be unpacked
        # Replicates logic from the original _DriverCacheManager__get_path
        driver_specific_cache_path = os.path.join(
            self._drivers_directory, # e.g., C:\Users\user\.wdm\drivers
            driver.get_name(),       # e.g., chromedriver
            self.get_os_type(),     # e.g., win64 (from our custom OS manager if used)
            driver.get_driver_version_to_download() # e.g., 116.0.5845.96
        )
        os.makedirs(driver_specific_cache_path, exist_ok=True)
        logging.info(f"[CustomDriverCacheManager] Driver files will be cached in: {driver_specific_cache_path}")

        archive_full_path = self._file_manager.save_archive_file(file_obj, driver_specific_cache_path)
        unpacked_files_relative_paths = self._file_manager.unpack_archive(archive_full_path, driver_specific_cache_path)
        logging.debug(f"[CustomDriverCacheManager] Unpacked files list from archive: {unpacked_files_relative_paths}")

        # Use our custom logic to find the binary name/subpath from the list of unpacked files
        binary_relative_path_in_archive = self._find_correct_binary(unpacked_files_relative_paths, driver.get_name())
        
        # Construct the full path to the actual executable binary
        actual_binary_full_path = os.path.join(driver_specific_cache_path, binary_relative_path_in_archive)
        logging.info(f"[CustomDriverCacheManager] Determined full path for binary: {actual_binary_full_path}")

        # Save metadata using this corrected binary path
        # Replicates logic from the original _DriverCacheManager__save_metadata
        current_date = date.today() # Changed to use date.today()
        metadata_content = self.load_metadata_content() # This is a public method
        
        # Replicates logic from _DriverCacheManager__get_metadata_key
        meta_os_type = self.get_os_type()
        meta_driver_name = driver.get_name()
        meta_driver_version = self.get_cache_key_driver_version(driver) # Public method
        meta_browser_version = driver.get_browser_version_from_os() or ""
        metadata_key = f"{meta_os_type}_{meta_driver_name}_{meta_driver_version}_for_{meta_browser_version}"
        logging.debug(f"[CustomDriverCacheManager] Metadata key for drivers.json: {metadata_key}")

        data_to_save_in_metadata = {
            metadata_key: {
                "timestamp": current_date.strftime(self._date_format), # _date_format is accessible
                "binary_path": actual_binary_full_path, # Crucial: our corrected path
            }
        }
        metadata_content.update(data_to_save_in_metadata)
        
        os.makedirs(self._root_dir, exist_ok=True) # Ensure root cache dir (e.g., ~/.wdm) exists for drivers.json
        with open(self._drivers_json_path, "w+") as outfile: # _drivers_json_path is accessible
            json.dump(metadata_content, outfile, indent=4)
        
        # Standard log message compatible with what might be expected by other parts or for consistency
        logging.info(f"Driver has been saved in cache [{driver_specific_cache_path}]. Custom binary path: {actual_binary_full_path}")
        return actual_binary_full_path

class CustomChromeDriverManager(ChromeDriverManager):
    def __init__(self,
                 driver_version: Optional[str] = None,
                 name: str = "chromedriver",
                 url: Optional[str] = None, 
                 latest_release_url: Optional[str] = None, 
                 chrome_type: str = ChromeType.GOOGLE,
                 download_manager: Optional[DownloadManager] = None,
                 os_system_manager: Optional[OperationSystemManager] = None):
        
        current_platform_os_type = None
        if platform.system() == "Windows":
            is_64bits = sys.maxsize > 2**32
            current_platform_os_type = "win64" if is_64bits else "win32"
        
        if os_system_manager is None:
            custom_os_manager_kwargs = {}
            if current_platform_os_type:
                custom_os_manager_kwargs['os_type'] = current_platform_os_type
            os_system_manager_to_pass = OperationSystemManager(**custom_os_manager_kwargs)
        else:
            os_system_manager_to_pass = os_system_manager

        custom_cache_manager = CustomDriverCacheManager()
        
        # Use standard defaults for URL and LATEST_RELEASE_URL if not provided by user
        # These are the defaults from webdriver_manager.chrome.ChromeDriverManager v4.0.1
        actual_url = url if url is not None else "https://chromedriver.storage.googleapis.com"
        actual_latest_release_url = latest_release_url if latest_release_url is not None else "https://chromedriver.storage.googleapis.com/LATEST_RELEASE"

        super().__init__(driver_version=driver_version,
                         name=name,
                         url=actual_url, 
                         latest_release_url=actual_latest_release_url,
                         chrome_type=chrome_type,
                         download_manager=download_manager,
                         cache_manager=custom_cache_manager,
                         os_system_manager=os_system_manager_to_pass)

    def get_os_type(self):
        # Ensures the os_type from our potentially customized os_system_manager is used.
        return self._os_system_manager.get_os_type()

# --- Discord Bot Setup ---
TOKEN = os.environ.get('DISCORD_BOT_TOKEN')  # Ensure you set your bot token as an environment variable
if not TOKEN:
    logging.error("Discord bot token not found in environment variables.")
    exit()

intents = discord.Intents.default()
intents.message_content = True # Required for reading message content for commands
intents.members = True # Required for checking member roles for admin commands

bot = commands.Bot(command_prefix='/', intents=intents)

# --- Constants ---
MONITORING_INTERVAL_SECONDS = 60  # 1 minute between checks (adjust as needed)
ADMIN_ROLE_NAME = os.environ.get('DISCORD_ADMIN_ROLE', "Bot Admin") # Configurable admin role name

# --- Helper Functions ---
def is_admin():
    """Custom check to see if the command invoker has the admin role or is the guild owner."""
    async def predicate(ctx):
        if ctx.guild: # Command invoked in a guild
            admin_role = discord.utils.get(ctx.guild.roles, name=ADMIN_ROLE_NAME)
            if admin_role and admin_role in ctx.author.roles:
                return True
            if ctx.author == ctx.guild.owner:
                return True
        # If not in a guild or no admin role/owner, not an admin
        return False
    return commands.check(predicate)

def format_timestamp(dt: datetime) -> str:
    """Formats a datetime object into a readable UTC string."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

async def fetch_website_content(url: str, requires_javascript: bool = False) -> Optional[str]:
    """
    Fetches the content of a website. Uses Selenium for JavaScript-rendered pages,
    otherwise uses aiohttp for static content.
    """
    try:
        if requires_javascript:
            logging.info(f"Fetching {url} using Selenium (requires_javascript=True).")
            try:
                # --- Start of Selenium setup ---
                # Use CustomChromeDriverManager with CustomDriverCacheManager
                custom_cache_manager = CustomDriverCacheManager()
                webdriver_path = CustomChromeDriverManager(
                    cache_manager=custom_cache_manager
                ).install()
                service = ChromeService(webdriver_path)

                options = webdriver.ChromeOptions()
                options.add_argument('--headless=new') # Use the new headless mode
                options.add_argument('--disable-gpu')
                options.add_argument('--no-sandbox')
                options.add_argument('--start-maximized')
                options.add_argument('--disable-dev-shm-usage')
                options.add_argument('--log-level=3') # Suppress verbose ChromeDriver logs
                # Keep the existing user-agent
                options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

                driver = webdriver.Chrome(service=service, options=options)
                logging.info(f"Selenium driver initialized for {url}.")
                # --- End of Selenium setup ---
                
                driver.get(url)
                # Wait for page to load, or for a specific element to be present
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
                content = driver.page_source
                driver.quit()
                return content
            except Exception as e: # This 'e' is the broader Selenium setup/initialization error
                logging.error(f"Error setting up or running Selenium for {url}: {e}")
                # Fall back to aiohttp
                return await fetch_with_aiohttp(url)
        else:
            return await fetch_with_aiohttp(url)
    except Exception as e:
        logging.error(f"Error fetching {url}: {e}")
        return None

async def fetch_with_aiohttp(url: str) -> Optional[str]:
    """Helper function to fetch content using aiohttp."""
    try:
        logging.info(f"Fetching {url} using aiohttp.")
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={'User-Agent': 'Mozilla/5.0'}) as response:
                response.raise_for_status() # Raise an exception for HTTP errors
                return await response.text()
    except aiohttp.ClientError as e:
        logging.error(f"HTTP error fetching {url} with aiohttp: {e}")
        return None
    except Exception as e:
        logging.error(f"Error fetching {url} with aiohttp: {e}")
        return None

async def check_stock_status(product: Dict[str, Any]) -> str:
    """
    Checks the stock status of a product by parsing the fetched HTML content.
    Returns "in_stock", "out_of_stock", or "unknown".
    """
    content = await fetch_website_content(product['url'], product.get('requires_javascript', False))
    if content:
        soup = BeautifulSoup(content, 'html.parser')
        try:
            # Special handling for Target
            if product['store_name'].lower() == 'target':
                page_text = soup.get_text().lower()
                
                # Check for definitive out-of-stock indicators first (higher priority)
                out_of_stock_indicators = [
                    "sold out",
                    "out of stock", 
                    "currently unavailable",
                    "temporarily out of stock", 
                    "not available"
                ]
                if any(indicator in page_text for indicator in out_of_stock_indicators):
                    logging.info(f"Found out-of-stock indicator for {product['name']}")
                    return "out_of_stock"
                
                # Count in-stock indicators
                in_stock_indicators = 0
                
                # Check 1: "add to cart" text in page
                if "add to cart" in page_text:
                    logging.info(f"Found 'add to cart' text for {product['name']}")
                    in_stock_indicators += 1
                
                # Check 2: Add to cart button exists
                add_to_cart_buttons = soup.select("button[data-test='shipItButton'], button.btn-primary")
                if add_to_cart_buttons:
                    for button in add_to_cart_buttons:
                        button_text = button.get_text().strip().lower()
                        if "add" in button_text and "cart" in button_text:
                            logging.info(f"Found add to cart button element for {product['name']}")
                            in_stock_indicators += 1
                            break
                
                # Check 3: Price is displayed (usually indicates in stock)
                price_elements = soup.select("[data-test='product-price'], .styles__CurrentPriceContainer-sc-z5703i-0, .style__PriceFontSize-sc-__sc-13aaghm-0")
                if price_elements:
                    logging.info(f"Found price element for {product['name']}")
                    in_stock_indicators += 1
                
                # Check 4: Ship it or pickup buttons (strong indicator of in-stock)
                shipping_elements = soup.select("[data-test='fulfillment-section']")
                if shipping_elements:
                    logging.info(f"Found shipping/pickup options for {product['name']}")
                    in_stock_indicators += 1
                
                # Decision logic - require at least two indicators for confidence
                if in_stock_indicators >= 2:
                    return "in_stock"
                elif in_stock_indicators == 0:
                    return "out_of_stock"  # No indicators at all
                else:
                    # Just one indicator - not enough confidence
                    logging.warning(f"Ambiguous stock status for {product['name']} - treating as out_of_stock until confirmed")
                    return "out_of_stock"
                
            else:
                # Non-Target stores use the standard checking method
                element = soup.select_one(product['css_selector_for_stock'])
                
                if element:
                    # Check text content
                    if product['expected_in_stock_text'].lower() in element.get_text(strip=True).lower():
                        return "in_stock"
                    # Check common attributes like 'class' or 'data-stock'
                    for attr in ['class', 'data-stock', 'data-status']:
                        if attr in element.attrs and product['expected_in_stock_text'].lower() in ' '.join(element.attrs[attr]).lower():
                            return "in_stock"
                    # If element found but expected text/attribute not present, assume out of stock
                    return "out_of_stock"
                else:
                    logging.warning(f"Could not find stock status element for {product['name']} (ID: {product['id']}) at {product['url']} using selector '{product['css_selector_for_stock']}'.")
                    return "unknown" # Element not found, status is unknown
        except Exception as e:
            logging.error(f"Error parsing stock status for {product['name']} (ID: {product['id']}) at {product['url']}: {e}")
            return "unknown"
    return "unknown" # Content could not be fetched

async def send_restock_notification(product: Dict[str, Any], subscriber_id: str):
    """
    Sends a restock notification to a specific subscribed channel/user.
    """
    embed = discord.Embed(
        title=f"🚨 RESTOCK ALERT! 🚨",
        color=discord.Color.green()
    )
    embed.add_field(name="Product", value=product['name'], inline=False)
    embed.add_field(name="Store", value=product['store_name'], inline=False)
    embed.add_field(name="Restocked At", value=format_timestamp(datetime.now(timezone.utc)), inline=False)
    embed.add_field(name="Checkout", value=f"🛒 [Click Here to Buy!]({product['checkout_url']}) ✨", inline=False)
    embed.set_thumbnail(url="https://placehold.co/100x100/00FF00/FFFFFF?text=POKEMON") # Placeholder image
    embed.set_footer(text="Powered by Pokémon Restock Bot | Happy Hunting!")

    try:
        # Try to get channel first, then user if it's a DM
        target_entity = bot.get_channel(int(subscriber_id))
        if not target_entity:
            target_entity = await bot.fetch_user(int(subscriber_id))

        if target_entity:
            await target_entity.send(embed=embed)
            logging.info(f"Restock notification sent to {target_entity.name} (ID: {subscriber_id}) for {product['name']}.")

            # Update last notified timestamp in Firestore
            sub_ref = db.collection('subscriptions').document(subscriber_id)
            sub_ref.update({f'last_notified_timestamps.{product["id"]}': firestore.SERVER_TIMESTAMP})
        else:
            logging.warning(f"Could not find Discord channel or user with ID {subscriber_id} to send notification.")
    except discord.Forbidden:
        logging.warning(f"Bot lacks permissions to send messages to {subscriber_id}.")
    except discord.HTTPException as e:
        logging.error(f"Discord API error sending notification to {subscriber_id}: {e}")
    except Exception as e:
        logging.error(f"Unexpected error sending notification to {subscriber_id}: {e}")

# --- Bot Commands ---
@bot.command(name='subscribe', help='Subscribe to restock alerts. Usage: /subscribe [product_keyword_or_id]')
async def subscribe(ctx, product_keyword_or_id: Optional[str] = None):
    """Subscribes the channel/user to restock alerts."""
    # Determine if it's a channel or a DM
    entity_id = str(ctx.channel.id) if ctx.guild else str(ctx.author.id)
    guild_id = str(ctx.guild.id) if ctx.guild else None # Guild ID is null for DMs

    sub_ref = db.collection('subscriptions').document(entity_id)
    sub_doc = sub_ref.get()

    if not sub_doc.exists:
        sub_ref.set({
            'discord_guild_id': guild_id,
            'subscribed_product_ids': [], # Initialize as empty list
            'notification_preference': 'specific_products', # Default to specific if no keyword, will be updated
            'last_notified_timestamps': {}
        })
        # Re-fetch the document after creation
        sub_doc = sub_ref.get()

    current_subscriptions = sub_doc.to_dict().get('subscribed_product_ids', [])
    
    if product_keyword_or_id is None:
        # Subscribe to all products
        all_products_docs = db.collection('monitored_products').where('is_active', '==', True).get()
        all_active_product_ids = [doc.id for doc in all_products_docs]
        
        sub_ref.update({
            'subscribed_product_ids': all_active_product_ids,
            'notification_preference': 'all_products'
        })
        await ctx.send(f"✅ This {'channel' if ctx.guild else 'user'} has subscribed to **all** currently monitored Pokémon card products.")
        logging.info(f"User/Channel {entity_id} subscribed to all products.")
    else:
        # Subscribe to a specific product
        product_to_subscribe_id = None
        
        # Try by exact ID first
        product_doc = db.collection('monitored_products').document(product_keyword_or_id).get()
        if product_doc.exists:
            product_to_subscribe_id = product_doc.id
        else:
            # Try by name (case-insensitive search)
            products_by_name = db.collection('monitored_products').where('name', '==', product_keyword_or_id).get()
            if products_by_name:
                product_to_subscribe_id = products_by_name[0].id # Take the first match
                product_doc = products_by_name[0] # Update product_doc for confirmation message

        if product_to_subscribe_id:
            if product_to_subscribe_id not in current_subscriptions:
                current_subscriptions.append(product_to_subscribe_id)
                sub_ref.update({
                    'subscribed_product_ids': list(set(current_subscriptions)), # Ensure unique
                    'notification_preference': 'specific_products'
                })
                product_name = product_doc.to_dict()['name']
                await ctx.send(f"✅ This {'channel' if ctx.guild else 'user'} has subscribed to restock alerts for '{product_name}'.")
                logging.info(f"User/Channel {entity_id} subscribed to product: {product_name} (ID: {product_to_subscribe_id}).")
            else:
                product_name = product_doc.to_dict()['name']
                await ctx.send(f"ℹ️ This {'channel' if ctx.guild else 'user'} is already subscribed to '{product_name}'.")
        else:
            await ctx.send(f"❌ Product with keyword/ID '{product_keyword_or_id}' not found. Please check `/list_monitored_products` for available items.")

@bot.command(name='unsubscribe', help='Unsubscribe from restock alerts. Usage: /unsubscribe [product_keyword_or_id]')
async def unsubscribe(ctx, product_keyword_or_id: Optional[str] = None):
    """Unsubscribes the channel/user from restock alerts."""
    entity_id = str(ctx.channel.id) if ctx.guild else str(ctx.author.id)
    sub_ref = db.collection('subscriptions').document(entity_id)
    sub_doc = sub_ref.get()

    if not sub_doc.exists:
        await ctx.send("ℹ️ This channel/user is not currently subscribed to any alerts.")
        return

    current_subscriptions = sub_doc.to_dict().get('subscribed_product_ids', [])

    if product_keyword_or_id is None:
        # Unsubscribe from all products
        sub_ref.update({'subscribed_product_ids': [], 'notification_preference': 'specific_products'})
        await ctx.send("✅ This {'channel' if ctx.guild else 'user'} has unsubscribed from **all** restock alerts.")
        logging.info(f"User/Channel {entity_id} unsubscribed from all products.")
    else:
        # Unsubscribe from a specific product
        product_to_unsubscribe_id = None
        product_name = None

        # Try by exact ID first
        product_doc = db.collection('monitored_products').document(product_keyword_or_id).get()
        if product_doc.exists:
            product_to_unsubscribe_id = product_doc.id
            product_name = product_doc.to_dict()['name']
        else:
            # Try by name (case-insensitive search)
            products_by_name = db.collection('monitored_products').where('name', '==', product_keyword_or_id).get()
            if products_by_name:
                product_to_unsubscribe_id = products_by_name[0].id
                product_name = products_by_name[0].to_dict()['name']

        if product_to_unsubscribe_id:
            if product_to_unsubscribe_id in current_subscriptions:
                current_subscriptions.remove(product_to_unsubscribe_id)
                sub_ref.update({
                    'subscribed_product_ids': current_subscriptions,
                    'notification_preference': 'specific_products' if current_subscriptions else 'all_products' # Adjust preference
                })
                await ctx.send(f"✅ This {'channel' if ctx.guild else 'user'} has unsubscribed from alerts for '{product_name}'.")
                logging.info(f"User/Channel {entity_id} unsubscribed from product: {product_name} (ID: {product_to_unsubscribe_id}).")
            else:
                await ctx.send(f"ℹ️ This {'channel' if ctx.guild else 'user'} was not subscribed to '{product_name}'.")
        else:
            await ctx.send(f"❌ Product with keyword/ID '{product_keyword_or_id}' not found.")

@bot.command(name='list_subscriptions', help='Displays all active subscriptions for the channel or user.')
async def list_subscriptions(ctx):
    """Lists all active subscriptions for the channel or user."""
    entity_id = str(ctx.channel.id) if ctx.guild else str(ctx.author.id)
    sub_ref = db.collection('subscriptions').document(entity_id)
    sub_doc = sub_ref.get()

    if not sub_doc.exists:
        await ctx.send("ℹ️ This channel/user is not currently subscribed to any alerts.")
        return

    sub_data = sub_doc.to_dict()
    subscribed_product_ids = sub_data.get('subscribed_product_ids', [])
    notification_preference = sub_data.get('notification_preference', 'specific_products')

    if notification_preference == 'all_products':
        await ctx.send("This {'channel' if ctx.guild else 'user'} is subscribed to alerts for **all** currently monitored products. ✨")
    elif subscribed_product_ids:
        product_names = []
        for product_id in subscribed_product_ids:
            product_doc = db.collection('monitored_products').document(product_id).get()
            if product_doc.exists:
                product_names.append(f"- **{product_doc.to_dict()['name']}** (ID: `{product_id}`)")
            else:
                product_names.append(f"- Unknown Product (ID: `{product_id}` - may have been removed)")
        
        embed = discord.Embed(
            title=f"Active Subscriptions for This {'Channel' if ctx.guild else 'User'}",
            description="\n".join(product_names),
            color=discord.Color.blue()
        )
        await ctx.send(embed=embed)
    else:
        await ctx.send("ℹ️ This {'channel' if ctx.guild else 'user'} has no specific product subscriptions. Use `/subscribe` to add some!")

@bot.command(name='list_monitored_products', help='Shows a list of all Pokémon card products the bot is currently configured to monitor.')
async def list_monitored_products(ctx):
    """Shows a list of all Pokémon card products the bot is currently configured to monitor."""
    products_query = db.collection('monitored_products').order_by('name')
    products = products_query.get()

    if not products:
        await ctx.send("ℹ️ No products are currently being monitored. Admins can add products using `/add_product`.")
        return

    product_list_str = []
    for product_doc in products:
        product_data = product_doc.to_dict()
        status = "Active" if product_data.get('is_active', True) else "Inactive"
        product_list_str.append(
            f"- **{product_data['name']}** (ID: `{product_doc.id}`)\n"
            f"  Store: {product_data['store_name']} | Status: {status}\n"
            f"  URL: <{product_data['url']}> | Checkout: <{product_data['checkout_url']}>\n"
            f"  Last Stock: `{product_data.get('last_stock_status', 'unknown')}` | Last Checked: {format_timestamp(product_data['last_checked']) if product_data.get('last_checked') else 'N/A'}"
        )
    
    # Discord embed has a character limit, split if necessary
    description_chunks = []
    current_chunk = []
    current_length = 0
    for item in product_list_str:
        if current_length + len(item) + 1 > 4000: # Max embed description length is 4096
            description_chunks.append("\n".join(current_chunk))
            current_chunk = [item]
            current_length = len(item)
        else:
            current_chunk.append(item)
            current_length += len(item) + 1
    if current_chunk:
        description_chunks.append("\n".join(current_chunk))

    for i, chunk in enumerate(description_chunks):
        embed = discord.Embed(
            title=f"Currently Monitored Pokémon Card Products (Page {i+1}/{len(description_chunks)})",
            description=chunk,
            color=discord.Color.purple()
        )
        await ctx.send(embed=embed)

@bot.command(name='add_product', help='Admin: Add a new product to monitor. Usage: /add_product [name] [store_name] [url] [checkout_url] [css_selector_for_stock] [expected_in_stock_text] [requires_javascript (true/false)]')
@is_admin()
async def add_product(ctx, name: str, store_name: str, url: str, checkout_url: str, css_selector_for_stock: str, expected_in_stock_text: str, requires_javascript_str: str):
    """Adds a new Pokémon card product for the bot to monitor (admin only)."""
    requires_javascript = requires_javascript_str.lower() == 'true'
    
    # Generate a more robust product ID (e.g., hash or auto-ID from Firestore)
    # For now, keeping the combination of store and name for simplicity as per prompt,
    # but noting it might not be truly unique if names are similar across stores.
    product_id_base = f"{store_name.lower().replace(' ', '_').replace('.', '')}_{name.lower().replace(' ', '_').replace('.', '')}"
    product_id = product_id_base
    counter = 0
    while (db.collection('monitored_products').document(product_id).get()).exists:
        counter += 1
        product_id = f"{product_id_base}_{counter}"

    product_data = {
        'name': name,
        'store_name': store_name,
        'url': url,
        'checkout_url': checkout_url,
        'css_selector_for_stock': css_selector_for_stock,
        'expected_in_stock_text': expected_in_stock_text,
        'last_stock_status': 'unknown',
        'last_checked': firestore.SERVER_TIMESTAMP,
        'last_restock_time': None, # Null initially
        'is_active': True,
        'requires_javascript': requires_javascript
    }
    try:
        db.collection('monitored_products').document(product_id).set(product_data)
        await ctx.send(f"✅ Product '{name}' from {store_name} added for monitoring with ID: `{product_id}`. It will be checked periodically.")
        logging.info(f"Admin {ctx.author.name} added product: {name} (ID: {product_id})")
    except Exception as e:
        await ctx.send(f"❌ Error adding product: {e}")
        logging.error(f"Error adding product '{name}': {e}")

@bot.command(name='remove_product', help='Admin: Remove a product from monitoring. Usage: /remove_product [product_id]')
@is_admin()
async def remove_product(ctx, product_id: str):
    """Removes a product from the monitoring list (admin only)."""
    try:
        product_doc = db.collection('monitored_products').document(product_id).get()
        if product_doc.exists:
            product_name = product_doc.to_dict()['name']
            db.collection('monitored_products').document(product_id).delete()
            
            # Remove this product from all subscriptions
            subscriptions_query = db.collection('subscriptions').where('subscribed_product_ids', 'array_contains', product_id)
            subscriptions_docs = subscriptions_query.get()
            
            for sub_doc in subscriptions_docs:
                sub_data = sub_doc.to_dict()
                updated_product_ids = [pid for pid in sub_data.get('subscribed_product_ids', []) if pid != product_id]
                db.collection('subscriptions').document(sub_doc.id).update({
                    'subscribed_product_ids': updated_product_ids,
                    'notification_preference': 'specific_products' if updated_product_ids else 'all_products' # Adjust preference
                })
                # Also remove from last_notified_timestamps
                if product_id in sub_data.get('last_notified_timestamps', {}):
                    db.collection('subscriptions').document(sub_doc.id).update({
                        f'last_notified_timestamps.{product_id}': firestore.DELETE_FIELD
                    })

            await ctx.send(f"✅ Product with ID '{product_id}' ('{product_name}') has been removed from monitoring and all relevant subscriptions updated.")
            logging.info(f"Admin {ctx.author.name} removed product: {product_name} (ID: {product_id})")
        else:
            await ctx.send(f"❌ Product with ID '{product_id}' not found.")
    except Exception as e:
        await ctx.send(f"❌ Error removing product: {e}")
        logging.error(f"Error removing product '{product_id}': {e}")

@bot.command(name='toggle_monitoring', help='Admin: Enable or disable monitoring for a product. Usage: /toggle_monitoring [product_id] [true/false]')
@is_admin()
async def toggle_monitoring(ctx, product_id: str, enable: str):
    """Enables or disables monitoring for a specific product (admin only)."""
    enable_bool = enable.lower() == 'true'
    try:
        product_ref = db.collection('monitored_products').document(product_id)
        product_doc = product_ref.get()

        if product_doc.exists:
            product_name = product_doc.to_dict()['name']
            product_ref.update({'is_active': enable_bool})
            status_text = "enabled" if enable_bool else "disabled"
            await ctx.send(f"✅ Monitoring for product '{product_name}' (ID: `{product_id}`) has been {status_text}.")
            logging.info(f"Admin {ctx.author.name} {status_text} monitoring for product: {product_name} (ID: {product_id})")
        else:
            await ctx.send(f"❌ Product with ID '{product_id}' not found.")
    except Exception as e:
        await ctx.send(f"❌ Error toggling monitoring for product: {e}")
        logging.error(f"Error toggling monitoring for product '{product_id}': {e}")

@bot.command(name='reset_all_statuses', help='Admin: Reset all product statuses to out_of_stock. Usage: /reset_all_statuses')
@is_admin()
async def reset_all_statuses(ctx):
    """Resets all product statuses to out_of_stock (admin only)."""
    try:
        # Get confirmation first
        confirm_message = await ctx.send("⚠️ This will reset ALL products to 'out_of_stock' status. Are you sure? Type 'yes' to confirm.")
        
        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel
        
        try:
            response = await bot.wait_for('message', check=check, timeout=30.0)
            if response.content.lower() != 'yes':
                await ctx.send("❌ Operation cancelled.")
                return
        except asyncio.TimeoutError:
            await ctx.send("❌ No confirmation received. Operation cancelled.")
            return
        
        # Get all active products
        products_query = db.collection('monitored_products')
        products_docs = products_query.get()
        
        if not products_docs:
            await ctx.send("❌ No products found to reset.")
            return
        
        # Update count
        updated_count = 0
        
        # Batch update all products
        batch = db.batch()
        for product_doc in products_docs:
            update_data = {
                'last_checked': firestore.SERVER_TIMESTAMP,
                'last_stock_status': 'out_of_stock'
            }
            batch.update(db.collection('monitored_products').document(product_doc.id), update_data)
            updated_count += 1
        
        # Commit the batch
        batch.commit()
        
        await ctx.send(f"✅ Successfully reset {updated_count} products to 'out_of_stock' status.")
        logging.info(f"Admin {ctx.author.name} reset all product statuses to out_of_stock ({updated_count} products updated).")
    except Exception as e:
        await ctx.send(f"❌ Error resetting product statuses: {e}")
        logging.error(f"Error resetting product statuses: {e}")

@bot.command(name='set_status', help='Admin: Manually set the stock status of a product. Usage: /set_status [product_id] [status] (status must be in_stock, out_of_stock, or unknown)')
@is_admin()
async def set_status(ctx, product_id: str, status: str):
    """Manually sets the stock status of a product (admin only)."""
    # Validate status value
    if status not in ["in_stock", "out_of_stock", "unknown"]:
        await ctx.send("❌ Invalid status. Status must be one of: in_stock, out_of_stock, unknown")
        return
    
    try:
        product_doc = db.collection('monitored_products').document(product_id).get()
        if product_doc.exists:
            product_data = product_doc.to_dict()
            product_name = product_data['name']
            
            # Update the status in the database
            update_data = {
                'last_checked': firestore.SERVER_TIMESTAMP,
                'last_stock_status': status
            }
            db.collection('monitored_products').document(product_id).update(update_data)
            
            await ctx.send(f"✅ Status for '{product_name}' (ID: `{product_id}`) has been manually set to '{status.upper()}'.")
            logging.info(f"Admin {ctx.author.name} manually set status for product: {product_name} (ID: {product_id}) to {status}")
        else:
            await ctx.send(f"❌ Product with ID '{product_id}' not found.")
    except Exception as e:
        await ctx.send(f"❌ Error setting product status: {e}")
        logging.error(f"Error setting status for product '{product_id}': {e}")

@bot.command(name='check_product', help='Admin: Check the current stock status of a product without sending notifications. Usage: /check_product [product_id]')
@is_admin()
async def check_product(ctx, product_id: str):
    """Checks the current stock status of a product without sending notifications (admin only)."""
    try:
        product_doc = db.collection('monitored_products').document(product_id).get()
        if product_doc.exists:
            product_data = product_doc.to_dict()
            product_data['id'] = product_id  # Add ID to product data for easier access
            
            await ctx.send(f"🔍 Checking stock status for '{product_data['name']}' (ID: `{product_id}`)...")
            
            current_stock_status = await check_stock_status(product_data)
            last_stock_status = product_data.get('last_stock_status', 'unknown')
            
            # Create an embed with the information
            embed = discord.Embed(
                title=f"Stock Status Check: {product_data['name']}",
                color=discord.Color.blue()
            )
            embed.add_field(name="Store", value=product_data['store_name'], inline=True)
            embed.add_field(name="Current Status", value=current_stock_status.upper(), inline=True)
            embed.add_field(name="Previous Status", value=last_stock_status.upper(), inline=True)
            embed.add_field(name="URL", value=f"[View Product]({product_data['url']})", inline=False)
            
            if current_stock_status == "in_stock":
                embed.add_field(name="Checkout", value=f"[Buy Now]({product_data['checkout_url']})", inline=False)
                embed.color = discord.Color.green()
            elif current_stock_status == "out_of_stock":
                embed.color = discord.Color.red()
            else:
                embed.color = discord.Color.light_grey()
                
            embed.set_footer(text=f"Last Checked: {format_timestamp(datetime.now(timezone.utc))}")
            
            await ctx.send(embed=embed)
            
            # Update the product's stock status in the database without triggering notifications
            update_data = {
                'last_checked': firestore.SERVER_TIMESTAMP,
                'last_stock_status': current_stock_status
            }
            db.collection('monitored_products').document(product_id).update(update_data)
            
            logging.info(f"Admin {ctx.author.name} manually checked product: {product_data['name']} (ID: {product_id}), Status: {current_stock_status}")
        else:
            await ctx.send(f"❌ Product with ID '{product_id}' not found.")
    except Exception as e:
        await ctx.send(f"❌ Error checking product: {e}")
        logging.error(f"Error checking product '{product_id}': {e}")

@bot.command(name='check_all_products', help='Admin: Check current stock status of all products without sending notifications. Usage: /check_all_products')
@is_admin()
async def check_all_products(ctx):
    """Checks the current stock status of all products without sending notifications (admin only)."""
    try:
        # Initial response
        status_msg = await ctx.send("🔍 Checking all products... This may take some time.")
        
        # Get all products
        products_query = db.collection('monitored_products')
        products_docs = products_query.get()
        
        if not products_docs:
            await ctx.send("❌ No products found to check.")
            return
        
        embed = discord.Embed(
            title="Stock Status Check - All Products",
            description="Current stock status for all monitored products:",
            color=discord.Color.blue()
        )
        
        in_stock_products = []
        out_of_stock_products = []
        unknown_products = []
        
        # Check each product
        for product_doc in products_docs:
            product_data = product_doc.to_dict()
            product_data['id'] = product_doc.id
            
            current_stock_status = await check_stock_status(product_data)
            last_stock_status = product_data.get('last_stock_status', 'unknown')
            
            # Update the database
            update_data = {
                'last_checked': firestore.SERVER_TIMESTAMP,
                'last_stock_status': current_stock_status
            }
            db.collection('monitored_products').document(product_data['id']).update(update_data)
            
            # Sort products by status
            product_info = f"**{product_data['name']}** - {product_data['store_name']} (ID: `{product_data['id']}`)"
            if current_stock_status == "in_stock":
                in_stock_products.append(product_info)
            elif current_stock_status == "out_of_stock":
                out_of_stock_products.append(product_info)
            else:
                unknown_products.append(product_info)
            
            # Add a small delay between checks to avoid rate limiting
            await asyncio.sleep(3)
        
        # Build embed with results
        if in_stock_products:
            embed.add_field(
                name="🟢 IN STOCK",
                value="\n".join(in_stock_products),
                inline=False
            )
        
        if out_of_stock_products:
            embed.add_field(
                name="🔴 OUT OF STOCK",
                value="\n".join(out_of_stock_products),
                inline=False
            )
        
        if unknown_products:
            embed.add_field(
                name="⚪ UNKNOWN STATUS",
                value="\n".join(unknown_products),
                inline=False
            )
        
        embed.set_footer(text=f"Last Checked: {format_timestamp(datetime.now(timezone.utc))}")
        
        # Delete the "checking" message and send results
        await status_msg.delete()
        await ctx.send(embed=embed)
        
        logging.info(f"Admin {ctx.author.name} checked all products. In stock: {len(in_stock_products)}, Out of stock: {len(out_of_stock_products)}, Unknown: {len(unknown_products)}")
    except Exception as e:
        await ctx.send(f"❌ Error checking products: {e}")
        logging.error(f"Error checking all products: {e}")

@bot.command(name='help_poke', help='Shows the list of all available commands')
async def help_poke(ctx):
    """Shows the detailed help for all commands, nicely formatted in an embed."""
    embed = discord.Embed(
        title="PokeAlert Bot Commands",
        description="Here are all the commands you can use with this bot:",
        color=discord.Color.blue()
    )
    
    # User Commands
    user_commands = [
        {"name": "/subscribe [product_keyword_or_id]", "value": "Subscribe to restock alerts for a specific product"},
        {"name": "/unsubscribe [product_keyword_or_id]", "value": "Unsubscribe from restock alerts for a specific product"},
        {"name": "/list_subscriptions", "value": "View all your active subscriptions"},
        {"name": "/list_monitored_products", "value": "See all products the bot is monitoring"}
    ]
    
    # Admin Commands
    admin_commands = [
        {"name": "/add_product [name] [store] [url] [checkout_url] [css_selector] [in_stock_text] [requires_js]", "value": "Add a new product to monitor"},
        {"name": "/remove_product [product_id]", "value": "Remove a product from monitoring"},
        {"name": "/toggle_monitoring [product_id] [true/false]", "value": "Enable/disable monitoring for a product"},
        {"name": "/check_product [product_id]", "value": "Check current stock status without notifications"},
        {"name": "/set_status [product_id] [status]", "value": "Manually set a product's stock status"},
        {"name": "/reset_all_statuses", "value": "Reset all products to out_of_stock status"},
        {"name": "/check_all_products", "value": "Check current stock status of all products without notifications"}
    ]
    
    # Add fields to embed
    embed.add_field(name="📱 User Commands", value="Commands available to all users:", inline=False)
    for cmd in user_commands:
        embed.add_field(name=cmd["name"], value=cmd["value"], inline=False)
    
    embed.add_field(name="⚙️ Admin Commands", value=f"Commands requiring the '{ADMIN_ROLE_NAME}' role:", inline=False)
    for cmd in admin_commands:
        embed.add_field(name=cmd["name"], value=cmd["value"], inline=False)
    
    embed.set_footer(text="For more details on each command, use /help [command_name]")
    
    await ctx.send(embed=embed)

# --- Background Task for Monitoring ---
@tasks.loop(seconds=MONITORING_INTERVAL_SECONDS)
async def monitor_restocks():
    """
    Background task that periodically checks for product restocks and sends notifications.
    """
    start_time = datetime.now()
    logging.info("Starting restock monitoring cycle...")
    
    # Fetch all active products
    active_products_query = db.collection('monitored_products').where('is_active', '==', True)
    products_docs = active_products_query.get()
    
    if not products_docs:
        logging.info("No active products to monitor.")
        return

    for product_doc in products_docs:
        product_data = product_doc.to_dict()
        product_data['id'] = product_doc.id # Add ID to product data for easier access

        current_stock_status = await check_stock_status(product_data)
        last_stock_status = product_data.get('last_stock_status', 'unknown')
        consecutive_oos_checks = product_data.get('consecutive_out_of_stock_checks', 0)
        
        logging.info(f"Checking {product_data['name']} (ID: {product_data['id']}): Current '{current_stock_status}', Last '{last_stock_status}', Consecutive OOS: {consecutive_oos_checks}")

        # Update tracking fields
        update_data = {
            'last_checked': firestore.SERVER_TIMESTAMP,
            'last_stock_status': current_stock_status
        }
        
        # Track consecutive out-of-stock checks
        if current_stock_status == "out_of_stock":
            update_data['consecutive_out_of_stock_checks'] = consecutive_oos_checks + 1
        elif current_stock_status == "in_stock":
            update_data['consecutive_out_of_stock_checks'] = 0
        
        # Restock detected: Strict conditions to prevent false positives
        # 1. Current status must be in_stock
        # 2. Last status must be out_of_stock
        # 3. Must have had at least 2 consecutive out_of_stock checks before this
        if current_stock_status == "in_stock" and last_stock_status == "out_of_stock" and consecutive_oos_checks >= 2:
            logging.info(f"RESTOCK DETECTED for {product_data['name']} (ID: {product_data['id']})!")
            update_data['last_restock_time'] = firestore.SERVER_TIMESTAMP
            
            # Find all relevant subscriptions
            # Option 1: Channels subscribed to this specific product_id
            specific_subs_query = db.collection('subscriptions').where('subscribed_product_ids', 'array_contains', product_data['id'])
            specific_subs = specific_subs_query.get()

            # Option 2: Channels subscribed to 'all_products'
            all_subs_query = db.collection('subscriptions').where('notification_preference', '==', 'all_products')
            all_subs = all_subs_query.get()
            
            # Combine and deduplicate subscriber IDs
            subscriber_ids = set()
            for sub_doc in specific_subs:
                subscriber_ids.add(sub_doc.id)
            for sub_doc in all_subs:
                subscriber_ids.add(sub_doc.id) # Add if not already present

            for subscriber_id in subscriber_ids:
                sub_doc = db.collection('subscriptions').document(subscriber_id).get()
                if sub_doc.exists:
                    sub_data = sub_doc.to_dict()
                    last_notified_timestamp_for_product = sub_data.get('last_notified_timestamps', {}).get(product_data['id'])
                    
                    # Only notify if this specific restock event hasn't been notified to this subscriber
                    # This check is crucial to prevent spamming the same restock repeatedly
                    if not last_notified_timestamp_for_product or \
                       (product_data['last_restock_time'] and last_notified_timestamp_for_product.to_datetime() < product_data['last_restock_time'].to_datetime()):
                        
                        # Ensure the last_restock_time in the database is actually newer than the last notification
                        # This handles cases where the bot restarts or the product was already in stock but not notified
                        
                        await send_restock_notification(product_data, subscriber_id)
                    else:
                        logging.info(f"Skipping notification for {product_data['name']} to {subscriber_id} as already notified for this restock.")
                else:
                    logging.warning(f"Subscription document {subscriber_id} not found during notification.")

        # Update product data in Firestore
        try:
            db.collection('monitored_products').document(product_data['id']).update(update_data)
        except Exception as e:
            logging.error(f"Error updating product {product_data['id']} in Firestore: {e}")

        # Add a small delay between product checks to avoid overwhelming sites
        await asyncio.sleep(5) # Adjust based on number of products and website policies

    # Calculate how long the cycle took
    end_time = datetime.now()
    elapsed_seconds = (end_time - start_time).total_seconds()
    logging.info(f"Restock monitoring cycle finished in {elapsed_seconds:.2f} seconds.")

# --- Bot Events ---
@bot.event
async def on_ready():
    """Called when the bot is ready and connected to Discord."""
    logging.info(f'Logged in as {bot.user.name} (ID: {bot.user.id})')
    logging.info('Bot is ready!')
    if not monitor_restocks.is_running():
        monitor_restocks.start()
        logging.info("Restock monitoring task started.")

@bot.event
async def on_command_error(ctx, error):
    """Global error handler for bot commands."""
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing argument(s). Please check the command usage. Type `/help {ctx.command.name}` for more info.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Invalid argument provided. Please check the command usage and argument types.")
    elif isinstance(error, commands.CommandNotFound):
        # Silently ignore if command not found, or send a subtle message
        # await ctx.send("❌ Unknown command. Type `/help` for a list of commands.")
        pass
    elif isinstance(error, commands.CheckFailure):
        await ctx.send("🚫 You do not have permission to use this command.")
    else:
        logging.error(f"Unhandled command error in {ctx.command}: {error}")
        await ctx.send(f"An unexpected error occurred: `{error}`. Please try again later or contact an administrator.")

# --- Run the bot ---
if __name__ == '__main__':
    bot.run(TOKEN)
