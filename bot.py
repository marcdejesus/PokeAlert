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
from datetime import datetime, timezone
import logging
from typing import Optional, List, Dict, Any

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
MONITORING_INTERVAL_SECONDS = 300  # 5 minutes between checks (adjust as needed)
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
            options = webdriver.ChromeOptions()
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--log-level=3') # Suppress verbose ChromeDriver logs
            service = ChromeService(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=options)
            driver.get(url)
            # Wait for page to load, or for a specific element to be present
            # This is a generic wait, consider making it more specific if needed
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            content = driver.page_source
            driver.quit()
            return content
        else:
            logging.info(f"Fetching {url} using aiohttp.")
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}) as response:
                    response.raise_for_status() # Raise an exception for HTTP errors
                    return await response.text()
    except aiohttp.ClientError as e:
        logging.error(f"HTTP error fetching {url} with aiohttp: {e}")
        return None
    except Exception as e:
        logging.error(f"Error fetching {url} with Selenium: {e}")
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
            await sub_ref.update({f'last_notified_timestamps.{product["id"]}': firestore.SERVER_TIMESTAMP})
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
    sub_doc = await sub_ref.get()

    if not sub_doc.exists:
        await sub_ref.set({
            'discord_guild_id': guild_id,
            'subscribed_product_ids': [], # Initialize as empty list
            'notification_preference': 'specific_products', # Default to specific if no keyword, will be updated
            'last_notified_timestamps': {}
        })
        # Re-fetch the document after creation
        sub_doc = await sub_ref.get()

    current_subscriptions = sub_doc.to_dict().get('subscribed_product_ids', [])
    
    if product_keyword_or_id is None:
        # Subscribe to all products
        all_products_docs = await db.collection('monitored_products').where('is_active', '==', True).get()
        all_active_product_ids = [doc.id for doc in all_products_docs]
        
        await sub_ref.update({
            'subscribed_product_ids': all_active_product_ids,
            'notification_preference': 'all_products'
        })
        await ctx.send(f"✅ This {'channel' if ctx.guild else 'user'} has subscribed to **all** currently monitored Pokémon card products.")
        logging.info(f"User/Channel {entity_id} subscribed to all products.")
    else:
        # Subscribe to a specific product
        product_to_subscribe_id = None
        
        # Try by exact ID first
        product_doc = await db.collection('monitored_products').document(product_keyword_or_id).get()
        if product_doc.exists:
            product_to_subscribe_id = product_doc.id
        else:
            # Try by name (case-insensitive search)
            products_by_name = await db.collection('monitored_products').where('name', '==', product_keyword_or_id).get()
            if products_by_name:
                product_to_subscribe_id = products_by_name[0].id # Take the first match
                product_doc = products_by_name[0] # Update product_doc for confirmation message

        if product_to_subscribe_id:
            if product_to_subscribe_id not in current_subscriptions:
                current_subscriptions.append(product_to_subscribe_id)
                await sub_ref.update({
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
    sub_doc = await sub_ref.get()

    if not sub_doc.exists:
        await ctx.send("ℹ️ This channel/user is not currently subscribed to any alerts.")
        return

    current_subscriptions = sub_doc.to_dict().get('subscribed_product_ids', [])

    if product_keyword_or_id is None:
        # Unsubscribe from all products
        await sub_ref.update({'subscribed_product_ids': [], 'notification_preference': 'specific_products'})
        await ctx.send("✅ This {'channel' if ctx.guild else 'user'} has unsubscribed from **all** restock alerts.")
        logging.info(f"User/Channel {entity_id} unsubscribed from all products.")
    else:
        # Unsubscribe from a specific product
        product_to_unsubscribe_id = None
        product_name = None

        # Try by exact ID first
        product_doc = await db.collection('monitored_products').document(product_keyword_or_id).get()
        if product_doc.exists:
            product_to_unsubscribe_id = product_doc.id
            product_name = product_doc.to_dict()['name']
        else:
            # Try by name (case-insensitive search)
            products_by_name = await db.collection('monitored_products').where('name', '==', product_keyword_or_id).get()
            if products_by_name:
                product_to_unsubscribe_id = products_by_name[0].id
                product_name = products_by_name[0].to_dict()['name']

        if product_to_unsubscribe_id:
            if product_to_unsubscribe_id in current_subscriptions:
                current_subscriptions.remove(product_to_unsubscribe_id)
                await sub_ref.update({
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
    sub_doc = await sub_ref.get()

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
            product_doc = await db.collection('monitored_products').document(product_id).get()
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
    products = await products_query.get()

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
    while (await db.collection('monitored_products').document(product_id).get()).exists:
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
        await db.collection('monitored_products').document(product_id).set(product_data)
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
        product_doc = await db.collection('monitored_products').document(product_id).get()
        if product_doc.exists:
            product_name = product_doc.to_dict()['name']
            await db.collection('monitored_products').document(product_id).delete()
            
            # Remove this product from all subscriptions
            subscriptions_query = db.collection('subscriptions').where('subscribed_product_ids', 'array_contains', product_id)
            subscriptions_docs = await subscriptions_query.get()
            
            for sub_doc in subscriptions_docs:
                sub_data = sub_doc.to_dict()
                updated_product_ids = [pid for pid in sub_data.get('subscribed_product_ids', []) if pid != product_id]
                await db.collection('subscriptions').document(sub_doc.id).update({
                    'subscribed_product_ids': updated_product_ids,
                    'notification_preference': 'specific_products' if updated_product_ids else 'all_products' # Adjust preference
                })
                # Also remove from last_notified_timestamps
                if product_id in sub_data.get('last_notified_timestamps', {}):
                    await db.collection('subscriptions').document(sub_doc.id).update({
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
        product_doc = await product_ref.get()

        if product_doc.exists:
            product_name = product_doc.to_dict()['name']
            await product_ref.update({'is_active': enable_bool})
            status_text = "enabled" if enable_bool else "disabled"
            await ctx.send(f"✅ Monitoring for product '{product_name}' (ID: `{product_id}`) has been {status_text}.")
            logging.info(f"Admin {ctx.author.name} {status_text} monitoring for product: {product_name} (ID: {product_id})")
        else:
            await ctx.send(f"❌ Product with ID '{product_id}' not found.")
    except Exception as e:
        await ctx.send(f"❌ Error toggling monitoring for product: {e}")
        logging.error(f"Error toggling monitoring for product '{product_id}': {e}")

# --- Background Task for Monitoring ---
@tasks.loop(seconds=MONITORING_INTERVAL_SECONDS)
async def monitor_restocks():
    """
    Background task that periodically checks for product restocks and sends notifications.
    """
    logging.info("Starting restock monitoring cycle...")
    
    # Fetch all active products
    active_products_query = db.collection('monitored_products').where('is_active', '==', True)
    products_docs = await active_products_query.get()
    
    if not products_docs:
        logging.info("No active products to monitor.")
        return

    for product_doc in products_docs:
        product_data = product_doc.to_dict()
        product_data['id'] = product_doc.id # Add ID to product data for easier access

        current_stock_status = await check_stock_status(product_data)
        last_stock_status = product_data.get('last_stock_status', 'unknown')
        
        logging.info(f"Checking {product_data['name']} (ID: {product_data['id']}): Current '{current_stock_status}', Last '{last_stock_status}'.")

        # Update last_checked timestamp
        update_data = {
            'last_checked': firestore.SERVER_TIMESTAMP,
            'last_stock_status': current_stock_status
        }
        
        # Restock detected: transition from out_of_stock/unknown to in_stock
        if current_stock_status == "in_stock" and last_stock_status in ["out_of_stock", "unknown"]:
            logging.info(f"RESTOCK DETECTED for {product_data['name']} (ID: {product_data['id']})!")
            update_data['last_restock_time'] = firestore.SERVER_TIMESTAMP
            
            # Find all relevant subscriptions
            # Option 1: Channels subscribed to this specific product_id
            specific_subs_query = db.collection('subscriptions').where('subscribed_product_ids', 'array_contains', product_data['id'])
            specific_subs = await specific_subs_query.get()

            # Option 2: Channels subscribed to 'all_products'
            all_subs_query = db.collection('subscriptions').where('notification_preference', '==', 'all_products')
            all_subs = await all_subs_query.get()
            
            # Combine and deduplicate subscriber IDs
            subscriber_ids = set()
            for sub_doc in specific_subs:
                subscriber_ids.add(sub_doc.id)
            for sub_doc in all_subs:
                subscriber_ids.add(sub_doc.id) # Add if not already present

            for subscriber_id in subscriber_ids:
                sub_doc = await db.collection('subscriptions').document(subscriber_id).get()
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
            await db.collection('monitored_products').document(product_data['id']).update(update_data)
        except Exception as e:
            logging.error(f"Error updating product {product_data['id']} in Firestore: {e}")

        # Add a small delay between product checks to avoid overwhelming sites
        await asyncio.sleep(5) # Adjust based on number of products and website policies

    logging.info("Restock monitoring cycle finished.")

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
