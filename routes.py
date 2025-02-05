from flask import Blueprint, jsonify, request
from bson import ObjectId
import logging
from json import JSONEncoder
from functools import wraps
from amazon_scrap import (
    get_department_id, get_soup, find_lowest_price_item,
    update_stock_status, login_amazon_and_continue, create_driver,
    navigate_to_orders_and_get_details
)
from database import product_collection, order_collection, sold_products_collection

# Custom JSONEncoder to handle ObjectId
class MongoJSONEncoder(JSONEncoder):
    def default(self, obj):
        return str(obj) if isinstance(obj, ObjectId) else super().default(obj)

# Create a Blueprint object
routes = Blueprint('routes', __name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def handle_exceptions(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            logger.error(f"Error in {f.__name__}: {e}")
            return jsonify({"error": str(e)}), 500
    return wrapper

def convert_objectid(doc):
    """Recursively convert ObjectId to string in dicts or lists."""
    if isinstance(doc, dict):
        return {k: str(v) if isinstance(v, ObjectId) else convert_objectid(v) for k, v in doc.items()}
    elif isinstance(doc, list):
        return [convert_objectid(item) for item in doc]
    return doc

def validate_objectid(id_str):
    try:
        return ObjectId(id_str)
    except:
        raise ValueError(f"Invalid ObjectId format: {id_str}")

# Routes
@routes.route('/', methods=['GET'])
def home():
    return jsonify({"message": "App is running"}), 200

@routes.route('/order_details', methods=['GET'])
@handle_exceptions
def get_order_details():
    driver = create_driver(headless=True)
    order_details = navigate_to_orders_and_get_details(driver)
    driver.quit()
    if order_details.get('success'):
        return jsonify({"message": "Order details retrieved successfully", "data": convert_objectid(order_details)}), 200
    return jsonify({"error": order_details.get('error')}), 500

@routes.route('/scrape_amazon', methods=['POST'])
@handle_exceptions
def scrape_amazon_endpoint():
    data = request.get_json()
    if not data or 'query' not in data:
        return jsonify({"error": "Missing required 'query' parameter"}), 400
    
    query, driver = data['query'], create_driver(headless=True)
    department = get_department_id(query)
    search_url = f"https://www.amazon.in/s?k={query}&i={department if department != 'all' else ''}"
    search_soup = get_soup(search_url, driver)
    
    items = search_soup.find_all("div", class_="s-result-item") if search_soup else []
    lowest_price_item = find_lowest_price_item(items, department)
    
    if not lowest_price_item:
        return jsonify({"error": "No suitable product found"}), 404
    
    update_stock_status(lowest_price_item)
    payment_success = login_amazon_and_continue(lowest_price_item['link'])
    lowest_price_item['price_history'] = [
        entry for i, entry in enumerate(lowest_price_item.get('price_history', []))
        if i == 0 or entry['price'] != lowest_price_item['price_history'][i-1]['price']
    ]
    
    response_data = {"lowest_price_product": convert_objectid(lowest_price_item), "payment_success": payment_success}
    if "price_drop" in lowest_price_item:
        price_drop = lowest_price_item["price_drop"]
        response_data["price_drop"] = {
            "message": f"Price dropped by ₹{price_drop['difference']:,.2f} ({price_drop['percentage']}%)",
            "details": price_drop
        }
    
    driver.quit()
    return jsonify(response_data), 200 if payment_success else 500

@routes.route('/get_products', methods=['GET'])
@handle_exceptions
def get_products():
    return jsonify({"products": convert_objectid(list(product_collection.find()))}), 200

@routes.route('/get_orders', methods=['GET'])
@handle_exceptions
def get_orders():
    return jsonify({"orders": convert_objectid(list(order_collection.find()))}), 200

@routes.route('/delete_product/<product_id>', methods=['DELETE'])
@handle_exceptions
def delete_product(product_id):
    result = product_collection.delete_one({"_id": validate_objectid(product_id)})
    return jsonify({"message": "Product deleted successfully"}) if result.deleted_count else jsonify({"error": "Product not found"}), 404

@routes.route('/delete_order/<order_id>', methods=['DELETE'])
@handle_exceptions
def delete_order(order_id):
    result = order_collection.delete_one({"_id": validate_objectid(order_id)})
    return jsonify({"message": "Order deleted successfully"}) if result.deleted_count else jsonify({"error": "Order not found"}), 404

@routes.route('/delete_all_products', methods=['DELETE'])
@handle_exceptions
def delete_all_products():
    return jsonify({"message": f"Deleted {product_collection.delete_many({}).deleted_count} products successfully"}), 200

@routes.route('/delete_all_orders', methods=['DELETE'])
@handle_exceptions
def delete_all_orders():
    return jsonify({"message": f"Deleted {order_collection.delete_many({}).deleted_count} orders successfully"}), 200

@routes.route('/sell_product', methods=['POST'])
@handle_exceptions
def sell_product():
    data = request.get_json()
    required_fields = ['order_id', 'selling_price', 'buyer_name', 'buyer_contact']
    
    if not data or any(field not in data for field in required_fields):
        return jsonify({"error": f"Missing required fields: {', '.join(required_fields)}"}), 400

    order_id = validate_objectid(data['order_id'])
    order = order_collection.find_one({"_id": order_id})
    
    if not order:
        return jsonify({"error": "Order not found"}), 404
    
    sold_product = {
        "order_id": order["order_id"],
        "product_title": order["product_title"],
        "delivery_date": order["delivery_date"],
        "current_status": "Sold",
        "selling_price": data["selling_price"],
        "buyer_name": data["buyer_name"],
        "buyer_contact": data["buyer_contact"],
        "sold_date": data.get("sold_date", "Not specified")
    }
    
    sold_products_collection.insert_one(sold_product)
    return jsonify({"message": "Product sold successfully", "sold_product": convert_objectid(sold_product)}), 201

@routes.route('/get_sold_product', methods=['POST'])
@handle_exceptions
def get_sold_product():
    data = request.get_json()
    if not data or ('order_id' not in data and 'buyer_name' not in data):
        return jsonify({"error": "Missing required fields: order_id or buyer_name"}), 400

    query = {}
    if 'order_id' in data:
        query['order_id'] = validate_objectid(data['order_id'])
    elif 'buyer_name' in data:
        query['buyer_name'] = data['buyer_name']

    sold_product = sold_products_collection.find_one(query)
    if not sold_product:
        return jsonify({"error": "Sold product not found"}), 404

    return jsonify({"message": "Sold product details retrieved successfully", "sold_product": convert_objectid(sold_product)}), 200
