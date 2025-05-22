# Pokémon Card Restock Discord Bot

This Discord bot is designed to help Pokémon TCG collectors stay updated on restocks of their favorite products across various online retailers. It monitors specified product pages and sends real-time notifications to Discord channels or users when a restock is detected.

## Features

- **Real-time Restock Alerts**: Get instant notifications when a product goes back in stock.
- **Flexible Subscription System**: Subscribe to all monitored products or specific items.
- **Admin Product Management**: Authorized users can add, remove, and manage products being monitored.
- **Intelligent Web Scraping**: Uses aiohttp/BeautifulSoup4 for static pages and Selenium for JavaScript-rendered content.
- **Persistent Storage**: Utilizes Firebase Firestore to store product data and user subscriptions.
- **Rate Limiting**: Implements delays to avoid overwhelming target websites.
- **Rich Discord Embeds**: Notifications are sent as appealing Discord embeds with direct checkout links.

## Technical Stack

- **Programming Language**: Python 3.8+
- **Discord Library**: discord.py
- **Web Scraping**: aiohttp, BeautifulSoup4, Selenium, webdriver-manager
- **Database**: Firebase Firestore (firebase-admin)
- **Scheduling**: asyncio for concurrent operations and discord.ext.tasks for periodic checks.

## Setup Guide

Follow the detailed instructions in [Setup_Instructions.md](Setup_Instructions.md) to get your bot up and running. This includes:

1. **Firebase Project Setup**: Creating a Firebase project, enabling Firestore, and generating service account credentials.
2. **Discord Bot Setup**: Creating a Discord application, adding a bot user, enabling necessary intents, and inviting the bot to your server.
3. **Environment Variables**: Configuring `DISCORD_BOT_TOKEN`, `FIREBASE_CREDENTIALS_PATH`, and optionally `DISCORD_ADMIN_ROLE`.
4. **Install Dependencies**: Using `pip install -r requirements.txt`.
5. **Run the Bot**: Executing `python bot.py`.

## Bot Commands

All commands are prefixed with `/`.

### User/Channel Commands

#### `/subscribe [product_keyword_or_id]`

Subscribes the current channel or direct message (DM) conversation to restock alerts.

- If `[product_keyword_or_id]` is omitted, subscribes to all currently monitored Pokémon card products.
- If a specific `product_keyword_or_id` (either the product's unique ID or its full name) is provided, the subscription is only for that item.

Examples:
```
/subscribe
/subscribe Charizard VMAX Rainbow Rare
/subscribe pokemon_center_charizard_vmax
```

#### `/unsubscribe [product_keyword_or_id]`

Allows the current channel or DM to stop receiving alerts.

- If `[product_keyword_or_id]` is omitted, all subscriptions for that channel/user are removed.
- If a specific `product_keyword_or_id` is provided, only that specific subscription is removed.

Examples:
```
/unsubscribe
/unsubscribe Charizard VMAX Rainbow Rare
```

#### `/list_subscriptions`

Displays all active subscriptions for the channel or user invoking the command.

#### `/list_monitored_products`

Shows a list of all Pokémon card products the bot is currently configured to monitor (name, store, URL, current status).

### Admin-Only Commands

These commands require the user to have a specific role (default: "Bot Admin", configurable via `DISCORD_ADMIN_ROLE` environment variable) or be the server owner.

#### `/add_product [name] [store_name] [url] [checkout_url] [css_selector_for_stock] [expected_in_stock_text] [requires_javascript (true/false)]`

Adds a new Pokémon card product for the bot to monitor.

- `name`: Descriptive name (e.g., "Charizard VMAX Rainbow Rare").
- `store_name`: Retailer name (e.g., "Pokémon Center").
- `url`: Direct URL to the product page.
- `checkout_url`: Direct link to add to cart or general checkout link.
- `css_selector_for_stock`: CSS selector for the HTML element indicating stock status (e.g., `.product-status span`, `.add-to-cart-button`).
- `expected_in_stock_text`: Text content that signifies "in stock" (e.g., "In Stock", "Add to Cart").
- `requires_javascript`: `true` if the page content loads dynamically (uses Selenium), `false` otherwise (uses aiohttp).

Example:
```
/add_product "Pikachu V Box" "Target" "https://www.target.com/pikachu-v-box" "https://www.target.com/cart" ".add-to-cart-button" "Add to Cart" false
```

#### `/remove_product [product_id]`

Removes a product from the monitoring list.

- `product_id`: The unique ID of the product (obtained from `/list_monitored_products`).

Example:
```
/remove_product target_pikachu_v_box
```

#### `/toggle_monitoring [product_id] [true/false]`

Enables or disables monitoring for a specific product without removing it from the database.

- `product_id`: The unique ID of the product.
- `true/false`: Set to `true` to enable, `false` to disable.

Example:
```
/toggle_monitoring target_pikachu_v_box false
```

## Error Handling & Logging

The bot includes basic error handling for commands and web scraping. All significant activities and errors are logged to the console, which is helpful for debugging and monitoring the bot's operation.

## Deployment Considerations

For continuous operation, the bot needs to be hosted on a reliable server that runs 24/7. Options include:

- **Virtual Private Server (VPS)**: Services like DigitalOcean, Linode, Vultr.
- **Cloud Platforms**: Google Cloud Run, AWS EC2, Azure App Service (requires Dockerization).
- **Dedicated Server**: For more control and resources.

Ensure your hosting environment has chromedriver installed if you intend to use `requires_javascript=true` for any monitored products. `webdriver-manager` attempts to manage this, but system-level dependencies might still be required.

## Contribution

Feel free to fork this repository, open issues, or submit pull requests for improvements and bug fixes.