What You Need to Do:
1. Firebase Project Setup
Go to the Firebase Console
Create a new project
Enable Firestore Database with production mode
Generate a service account key:
Go to Project settings > Service accounts
Click "Generate new private key"
Save the downloaded JSON as firebase_credentials.json in the project directory
2. Discord Bot Setup
Go to the Discord Developer Portal
Create a new application and bot
Copy the bot token
Enable the required intents:
PRESENCE INTENT
SERVER MEMBERS INTENT
MESSAGE CONTENT INTENT
Generate an invite URL with the necessary permissions and invite the bot to your server
3. Set Environment Variables
Set the following environment variables:
DISCORD_BOT_TOKEN: Your Discord bot token
FIREBASE_CREDENTIALS_PATH: Path to your firebase_credentials.json file (can be relative)
DISCORD_ADMIN_ROLE: (Optional) The name of the admin role, defaults to "Bot Admin"
For Windows (PowerShell):
Apply to README.md
Run
4. Run the Bot
After completing the above steps, run the bot:
Apply to README.md
Important Notes:
You'll need to set up a Discord server and create a role named "Bot Admin" (or whatever you specified in the environment variable) to use admin commands
The bot requires internet access to monitor product pages
Make sure to secure your firebase_credentials.json file as it contains sensitive information
For production deployment, consider using a VPS or cloud service for 24/7 availability
Once the bot is running, you can use the commands listed in the README to manage subscriptions and monitor products.