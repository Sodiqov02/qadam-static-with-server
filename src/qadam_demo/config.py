import os
from dotenv import load_dotenv

def load_config():
    load_dotenv()
    
    bot_token = os.getenv("BOT_TOKEN")
    admin_id = int(os.getenv("ADMIN_ID", "0"))
    bot_username = os.getenv("BOT_USERNAME", "")

    if not bot_token:
        raise RuntimeError("BOT_TOKEN is empty. Create .env")
    if not admin_id:
        raise RuntimeError("ADMIN_ID is empty/int")
        
    return {
        "BOT_TOKEN": bot_token,
        "ADMIN_ID": admin_id,
        "BOT_USERNAME": bot_username
    }