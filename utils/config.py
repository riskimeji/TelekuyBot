from dotenv import load_dotenv
import os

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
LARAVEL_API_URL: str = os.getenv("LARAVEL_API_URL", "http://localhost:8000/api")
BOT_SECRET: str = os.getenv("BOT_SECRET", "")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORAGE_DIR = os.path.join(BASE_DIR, "storage")
DATA_DIR = os.path.join(BASE_DIR, "data")


# Pastikan folder storage ada
os.makedirs(STORAGE_DIR, exist_ok=True)

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN belum diset di .env!")