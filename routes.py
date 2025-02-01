from flask import Blueprint, jsonify, request
from database import product_collection, order_collection
from bson import ObjectId
from amazon_scrap import (
    get_department_id,
    get_soup,
    find_lowest_price_item,
    update_stock_status,
    login_amazon_and_continue,
    create_driver
)
import logging

# Create a Blueprint object
routes = Blueprint('routes', __name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def convert_objectid(doc):
    """Convert ObjectId to string for JSON serialization."""
    if "_id" in doc and isinstance(doc["_id"], ObjectId):
        doc["_id"] = str(doc["_id"])
    return doc

def build_search_url(query, department):
    """Build the search URL based on the query and department."""
    base_url = f"https://www.amazon.in/s?k={query}"
    if department != 'all':
        base_url += f"&i={department}"
    base_url += "&rh=n%3A976419031%2Cp_n_format_browse-bin%3A19150304031"
    return base_url

def fetch_lowest_price_item(query, department, driver):
    """Fetch the lowest price item from Amazon."""
    search_url = build_search_url(query, department)
    search_soup = get_soup(search_url, driver)
    if not search_soup:
        return None
    
    items = search_soup.find_all("div", class_="s-result-item")
    lowest_price_item = find_lowest_price_item(items, department)
    
    if not lowest_price_item:
        search_soup = get_soup(build_search_url(query, 'all'), driver)
        items = search_soup.find_all("div", class_="s-result-item")
        lowest_price_item = find_lowest_price_item(items, department)
    
    return lowest_price_item

@routes.route('/scrape_amazon', methods=['POST'])
def scrape_amazon_endpoint():
    """Endpoint to scrape Amazon for the lowest price item."""
    data = request.json
    if not data or 'query' not in data:
        return jsonify({"error": "Missing required 'query' parameter"}), 400
    
    query = data['query']
    department = get_department_id(query)
    driver = create_driver(headless=True)
    
    try:
        lowest_price_item = fetch_lowest_price_item(query, department, driver)
        if not lowest_price_item:
            return jsonify({"error": "No suitable product found"}), 404
        
        update_stock_status(lowest_price_item)
        payment_success, order_details = login_amazon_and_continue(lowest_price_item['link'])
        
        response_data = {
            "lowest_price_product": lowest_price_item,
            "payment_success": payment_success,
            "order_details": order_details
        }
        
        if not order_details.get('success', False):
            return jsonify(response_data), 500
            
        return jsonify(response_data), 200
    
    except Exception as e:
        logger.error(f"Error during scraping: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        driver.quit()

@routes.route('/get_products', methods=['GET'])
def get_products():
    """Endpoint to fetch all products."""
    products = list(product_collection.find())
    return jsonify({"products": [convert_objectid(p) for p in products]}), 200

@routes.route('/get_orders', methods=['GET'])
def get_orders():
    """Endpoint to fetch all orders."""
    orders = list(order_collection.find())
    return jsonify({"orders": [convert_objectid(o) for o in orders]}), 200

@routes.route('/delete_product/<product_id>', methods=['DELETE'])
def delete_product(product_id):
    """Endpoint to delete a product by its ID."""
    try:
        # Convert string ID to ObjectId
        obj_id = ObjectId(product_id)
        result = product_collection.delete_one({"_id": obj_id})
        
        if result.deleted_count == 1:
            return jsonify({"message": "Product deleted successfully"}), 200
        else:
            return jsonify({"error": "Product not found"}), 404
    
    except Exception as e:
        logger.error(f"Error deleting product: {e}")
        return jsonify({"error": str(e)}), 500

@routes.route('/delete_order/<order_id>', methods=['DELETE'])
def delete_order(order_id):
    """Endpoint to delete an order by its ID."""
    try:
        # Convert string ID to ObjectId
        obj_id = ObjectId(order_id)
        result = order_collection.delete_one({"_id": obj_id})
        
        if result.deleted_count == 1:
            return jsonify({"message": "Order deleted successfully"}), 200
        else:
            return jsonify({"error": "Order not found"}), 404
    
    except Exception as e:
        logger.error(f"Error deleting order: {e}")
        return jsonify({"error": str(e)}), 500
    
@routes.route('/delete_all_products', methods=['DELETE'])
def delete_all_products():
    """Endpoint to delete all products."""
    try:
        result = product_collection.delete_many({})  # Delete all documents
        return jsonify({
            "message": f"Deleted {result.deleted_count} products successfully"
        }), 200
    except Exception as e:
        logger.error(f"Error deleting all products: {e}")
        return jsonify({"error": str(e)}), 500

@routes.route('/delete_all_orders', methods=['DELETE'])
def delete_all_orders():
    """Endpoint to delete all orders."""
    try:
        result = order_collection.delete_many({})  # Delete all documents
        return jsonify({
            "message": f"Deleted {result.deleted_count} orders successfully"
        }), 200
    except Exception as e:
        logger.error(f"Error deleting all orders: {e}")
        return jsonify({"error": str(e)}), 500