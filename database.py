from pymongo import MongoClient
import os
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# MongoDB Configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "amazon_scraper_db")

def get_database_connection():
    """Establish and return a MongoDB database connection."""
    try:
        client = MongoClient(MONGO_URI)
        db = client[MONGO_DB_NAME]
        logger.info(f"MongoDB connected successfully to database: {MONGO_DB_NAME}")
        return db
    except Exception as e:
        logger.error(f"Error connecting to MongoDB: {e}")
        return None

def get_collections(db):
    """Get product and order collections from the database."""
    if db is not None:
        product_collection = db["products"]
        order_collection = db["orders"]
        return product_collection, order_collection
    return None, None

# Initialize database connection and collections
database = get_database_connection()
product_collection = None
order_collection = None
if database is not None:
    product_collection, order_collection = get_collections(database)