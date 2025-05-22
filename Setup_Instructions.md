# Setting up the Pokémon Card Restock Discord Bot

This guide will walk you through setting up your Firebase project, configuring your Discord bot, and deploying the Python script.

## 1. Firebase Project Setup

### Create a Firebase Project:
1. Go to the [Firebase Console](https://console.firebase.google.com/).
2. Click "Add project" and follow the steps to create a new project.

### Enable Firestore Database:
1. In your Firebase project, navigate to "Build" > "Firestore Database".
2. Click "Create database".
3. Choose "Start in production mode" (you will set up security rules later if needed, but for this bot, direct access via service account is used).
4. Select a Cloud Firestore location.

### Generate a Service Account Key:
1. In your Firebase project, go to "Project settings" (gear icon next to "Project overview").
2. Click on "Service accounts".
3. Click "Generate new private key" and then "Generate key".
4. A JSON file containing your service account credentials will be downloaded. Rename this file to `firebase_credentials.json` and place it in the same directory as your `bot.py` script. Keep this file secure and do not share it publicly.

## 2. Discord Bot Setup

### Create a New Application:
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click "New Application". Give it a name (e.g., "Pokemon Restock Bot") and click "Create".

### Create a Bot User:
1. In your application, go to the "Bot" tab on the left sidebar.
2. Click "Add Bot" and confirm.

### Copy the Bot Token: 
1. Under "TOKEN", click "Copy". This is your `DISCORD_BOT_TOKEN`. Keep it secret!

### Enable Intents: 
1. Scroll down to "Privileged Gateway Intents" and enable:
   - PRESENCE INTENT (optional, but good for bot status)
   - SERVER MEMBERS INTENT (required for checking admin roles)
   - MESSAGE CONTENT INTENT (required for bot to read command messages)

### Invite the Bot to Your Server:
1. Go to the "OAuth2" > "URL Generator" tab.
2. Under "SCOPES", select `bot`.
3. Under "BOT PERMISSIONS", select the necessary permissions. At a minimum, your bot will need:
   - Read Messages/View Channels
   - Send Messages
   - Embed Links (for rich notifications)
   - Manage Webhooks (if you plan to use webhooks for notifications, though this bot uses direct messages)
4. Copy the generated URL and paste it into your browser. Select the Discord server you want to invite the bot to and authorize it.

## 3. Environment Variables

The bot uses environment variables for sensitive information.

- **DISCORD_BOT_TOKEN**: The token you copied from the Discord Developer Portal.
- **FIREBASE_CREDENTIALS_PATH**: The path to your `firebase_credentials.json` file. By default, it looks for `firebase_credentials.json` in the same directory as `bot.py`.
- **DISCORD_ADMIN_ROLE**: (Optional) The name of the Discord role that will have admin privileges for the bot's product management commands (e.g., "Bot Admin"). If not set, it defaults to "Bot Admin".

### How to set environment variables:

#### Linux/macOS (Terminal):
```bash
export DISCORD_BOT_TOKEN="YOUR_BOT_TOKEN_HERE"
export FIREBASE_CREDENTIALS_PATH="/path/to/your/firebase_credentials.json"
export DISCORD_ADMIN_ROLE="Your Admin Role Name" # Optional
```
Note: These are session-specific. For persistent variables, add them to your `~/.bashrc`, `~/.zshrc`, or equivalent.

#### Windows (Command Prompt):
```cmd
set DISCORD_BOT_TOKEN="YOUR_BOT_TOKEN_HERE"
set FIREBASE_CREDENTIALS_PATH="C:\path\to\your\firebase_credentials.json"
set DISCORD_ADMIN_ROLE="Your Admin Role Name" # Optional
```
Note: For persistent variables, use System Properties > Environment Variables.

#### When running with python command directly:
You can also set them inline (for testing, not recommended for production):
```bash
DISCORD_BOT_TOKEN="YOUR_BOT_TOKEN" FIREBASE_CREDENTIALS_PATH="firebase_credentials.json" python bot.py
```

## 4. Install Dependencies

1. Make sure you have Python 3.8+ installed.

2. Save `requirements.txt`: Create a file named `requirements.txt` in the same directory as your `bot.py` with the following content:
```
discord.py==2.3.2
aiohttp==3.9.5
beautifulsoup4==4.12.3
selenium==4.21.0
webdriver-manager==4.0.1
firebase-admin==6.5.0
```

3. Install: Open your terminal or command prompt in the directory where you saved the files and run:
```bash
pip install -r requirements.txt
```

## 5. Run the Bot

Once all dependencies are installed and environment variables are set, you can run the bot:
```bash
python bot.py
```

The bot should come online in your Discord server. Check the terminal output for any errors.