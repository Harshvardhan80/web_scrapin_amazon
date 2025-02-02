from flask import Blueprint, jsonify, request, Flask
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
from json import JSONEncoder
from functools import wraps

# Custom JSONEncoder to handle ObjectId
class MongoJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        return super().default(obj)

# Create a Blueprint object
routes = Blueprint('routes', __name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def handle_exceptions(f):
    """Decorator to handle common exceptions."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except ValueError as e:
            logger.error(f"Invalid input: {e}")
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            logger.error(f"Unexpected error in {f.__name__}: {e}")
            return jsonify({"error": str(e)}), 500
    return wrapper

def convert_objectid(doc):
    """Convert ObjectId to string for JSON serialization."""
    if isinstance(doc, dict):
        return {k: str(v) if isinstance(v, ObjectId) else convert_objectid(v) if isinstance(v, (dict, list)) else v
                for k, v in doc.items()}
    elif isinstance(doc, list):
        return [convert_objectid(item) for item in doc]
    return doc

def validate_objectid(id_str):
    """Validate and convert string to ObjectId."""
    try:
        return ObjectId(id_str)
    except:
        raise ValueError(f"Invalid ObjectId format: {id_str}")

@routes.route('/scrape_amazon', methods=['POST'])
@handle_exceptions
def scrape_amazon_endpoint():
    """Endpoint to scrape Amazon for the lowest price item."""
    data = request.get_json()
    if not data or 'query' not in data:
        return jsonify({"error": "Missing required 'query' parameter"}), 400
    
    query = data['query']
    department = get_department_id(query)
    driver = None
    
    try:
        driver = create_driver(headless=True)
        lowest_price_item = fetch_lowest_price_item(query, department, driver)
        
        if not lowest_price_item:
            return jsonify({"error": "No suitable product found"}), 404
        
        update_stock_status(lowest_price_item)
        payment_success, order_details = login_amazon_and_continue(lowest_price_item['link'])
        
        response_data = {
            "lowest_price_product": convert_objectid(lowest_price_item),
            "payment_success": payment_success,
            "order_details": convert_objectid(order_details)
        }
        
        return jsonify(response_data), 200 if order_details.get('success', False) else 500
    
    finally:
        if driver:
            driver.quit()

def fetch_lowest_price_item(query, department, driver):
    """Fetch the lowest price item from Amazon."""
    search_url = build_search_url(query, department)
    search_soup = get_soup(search_url, driver)
    
    if not search_soup:
        return None
    
    items = search_soup.find_all("div", class_="s-result-item")
    lowest_price_item = find_lowest_price_item(items, department)
    
    if not lowest_price_item and department != 'all':
        search_soup = get_soup(build_search_url(query, 'all'), driver)
        if search_soup:
            items = search_soup.find_all("div", class_="s-result-item")
            lowest_price_item = find_lowest_price_item(items, department)
    
    return lowest_price_item

def build_search_url(query, department):
    """Build the search URL based on the query and department."""
    base_url = f"https://www.amazon.in/s?k={query}"
    if department != 'all':
        base_url += f"&i={department}"
    base_url += "&rh=n%3A976419031%2Cp_n_format_browse-bin%3A19150304031"
    return base_url

def create_app():
    """Create and configure Flask application."""
    app = Flask(__name__)
    app.json_encoder = MongoJSONEncoder
    app.register_blueprint(routes)
    return app

# Add root route to handle requests to the root URL
@routes.route('/')
def home():
    return "Service is running!"

@routes.route('/get_products', methods=['GET'])
@handle_exceptions
def get_products():
    """Endpoint to fetch all products."""
    products = list(product_collection.find())
    return jsonify({"products": convert_objectid(products)}), 200

@routes.route('/get_orders', methods=['GET'])
@handle_exceptions
def get_orders():
    """Endpoint to fetch all orders."""
    orders = list(order_collection.find())
    return jsonify({"orders": convert_objectid(orders)}), 200

@routes.route('/delete_product/<product_id>', methods=['DELETE'])
@handle_exceptions
def delete_product(product_id):
    """Endpoint to delete a product by its ID."""
    obj_id = validate_objectid(product_id)
    result = product_collection.delete_one({"_id": obj_id})
    
    if result.deleted_count == 1:
        return jsonify({"message": "Product deleted successfully"}), 200
    return jsonify({"error": "Product not found"}), 404

@routes.route('/delete_order/<order_id>', methods=['DELETE'])
@handle_exceptions
def delete_order(order_id):
    """Endpoint to delete an order by its ID."""
    obj_id = validate_objectid(order_id)
    result = order_collection.delete_one({"_id": obj_id})
    
    if result.deleted_count == 1:
        return jsonify({"message": "Order deleted successfully"}), 200
    return jsonify({"error": "Order not found"}), 404

@routes.route('/delete_all_products', methods=['DELETE'])
@handle_exceptions
def delete_all_products():
    """Endpoint to delete all products."""
    result = product_collection.delete_many({})
    return jsonify({
        "message": f"Deleted {result.deleted_count} products successfully"
    }), 200

@routes.route('/delete_all_orders', methods=['DELETE'])
@handle_exceptions
def delete_all_orders():
    """Endpoint to delete all orders."""
    result = order_collection.delete_many({})
    return jsonify({
        "message": f"Deleted {result.deleted_count} orders successfully"
    }), 200
