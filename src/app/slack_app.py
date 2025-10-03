"""
Slack app instance module to avoid circular imports.
"""
import os
from dotenv import load_dotenv
from slack_bolt.async_app import AsyncApp

# Load environment variables
load_dotenv()
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]

# Initialize the Bolt app
app = AsyncApp(token=SLACK_BOT_TOKEN)
