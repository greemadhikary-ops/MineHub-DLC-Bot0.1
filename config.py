# config.py - Configuration file for Telegram Stream Bot

import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(".env")

class Config:
    # Telegram API Credentials (Required)
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    
    # Owner ID for bot administration (Required)
    OWNER_ID = int(os.environ.get("OWNER_ID", 0))
    
    # Storage Channel - Where files are stored (Required)
    # Can be numeric ID (-100xxxxxxxx) or username (@channel)
    _storage_channel_str = os.environ.get("STORAGE_CHANNEL")
    if _storage_channel_str:
        try: 
            STORAGE_CHANNEL = int(_storage_channel_str)
        except ValueError: 
            STORAGE_CHANNEL = _storage_channel_str
    else: 
        STORAGE_CHANNEL = 0
    
    # Base URL for your web application (Required)
    # Example: https://your-domain.com
    BASE_URL = os.environ.get("BASE_URL", "").rstrip('/')
    
    # Database URL for MongoDB (Required)
    DATABASE_URL = os.environ.get("DATABASE_URL", "")
    
    # Optional: Redirect URL for blogger integration
    REDIRECT_BLOGGER_URL = os.environ.get("REDIRECT_BLOGGER_URL", "")
    
    # Optional: Blogger page URL
    BLOGGER_PAGE_URL = os.environ.get("BLOGGER_PAGE_URL", "")
    
    # Force Subscribe Channel Configuration
    # Users must join this channel before accessing files
    # Can be numeric ID (-100xxxxxxxx) or username (@channel)
    # Set to 0 or empty to disable force subscribe
    _fsub_channel_str = os.environ.get("FORCE_SUB_CHANNEL")
    if _fsub_channel_str:
        try: 
            FORCE_SUB_CHANNEL = int(_fsub_channel_str)
        except ValueError: 
            FORCE_SUB_CHANNEL = _fsub_channel_str
    else: 
        FORCE_SUB_CHANNEL = 0
    
    # Bot username - Automatically set by the bot at startup
    # No need to manually configure this
    BOT_USERNAME = ""
    
    # File Type Settings
    # Supported file extensions (automatically handled)
    SUPPORTED_EXTENSIONS = ['.mcaddon', '.mcpack', '.video', '.audio']
    
    # MCaddon specific settings
    MCADDON_ENABLED = True  # Enable MCaddon support
    MCADDON_EXTENSIONS = ['.mcaddon', '.mcpack']
    
    @classmethod
    def validate(cls):
        """Validate required configuration"""
        errors = []
        
        if not cls.API_ID:
            errors.append("API_ID is required")
        if not cls.API_HASH:
            errors.append("API_HASH is required")
        if not cls.BOT_TOKEN:
            errors.append("BOT_TOKEN is required")
        if not cls.OWNER_ID:
            errors.append("OWNER_ID is required")
        if not cls.STORAGE_CHANNEL:
            errors.append("STORAGE_CHANNEL is required")
        if not cls.BASE_URL:
            errors.append("BASE_URL is required")
        if not cls.DATABASE_URL:
            errors.append("DATABASE_URL is required")
        
        if errors:
            raise ValueError("\n".join(errors))
        
        return True
