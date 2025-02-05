import os
import time
import logging
from dotenv import load_dotenv
from datetime import datetime
from flask import Flask, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup
from database import product_collection, order_collection

# Load environment variables
load_dotenv()

# Retrieve credentials from environment variables
AMAZON_EMAIL = os.getenv("AMAZON_EMAIL")
AMAZON_PASSWORD = os.getenv("AMAZON_PASSWORD")
AMAZON_CVV = os.getenv("AMAZON_CVV")

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_department_id(query):
    """
    Map common products to their department IDs.
    
    Args:
        query (str): Product search query
    
    Returns:
        str: Department identifier
    """
    product_departments = {
        'iphone': 'electronics',
        'samsung': 'electronics',
        'macbook': 'computers',
        'laptop': 'computers',
        'ipad': 'electronics',
    }
    
    query_lower = query.lower()
    for key, department in product_departments.items():
        if key in query_lower:
            return department
    return 'all'

def create_driver(headless=True):
    """
    Create a configured Selenium WebDriver for Chrome.
    
    Args:
        headless (bool): Run browser in headless mode
    
    Returns:
        webdriver.Chrome: Configured Chrome WebDriver
    """
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # Path to the pre-installed Chrome
    options.binary_location = "/usr/bin/google-chrome-stable"
    
    if headless:
        options.add_argument("--headless")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def get_soup(url, driver):
    """
    Retrieve webpage source and parse with BeautifulSoup.
    
    Args:
        url (str): Webpage URL
        driver (webdriver.Chrome): Selenium WebDriver
    
    Returns:
        BeautifulSoup: Parsed webpage or None
    """
    try:
        driver.get(url)
        time.sleep(5)
        page_source = driver.page_source
        
        if "Enter the characters you see below" in page_source:
            logger.warning("⚠️ Amazon CAPTCHA detected. Solve it manually and continue.")
            return None
        
        return BeautifulSoup(page_source, "html.parser")
    except TimeoutException:
        logger.error("Timeout occurred while loading the page.")
        return None
    except Exception as e:
        logger.error(f"Error fetching page: {e}")
        return None

def save_to_db(collection, data, key):
    """
    Save or update data in MongoDB collection.
    
    Args:
        collection: MongoDB collection
        data (dict): Data to save
        key (str): Unique identifier key
    """
    try:
        existing_record = collection.find_one({key: data[key]})
        if existing_record:
            collection.update_one({key: data[key]}, {"$set": data})
        else:
            collection.insert_one(data)
    except Exception as e:
        logger.error(f"Error saving to database: {e}")

def extract_product_details(item):
    """
    Extract detailed product information from BeautifulSoup item.
    
    Args:
        item (BeautifulSoup): Product item
    
    Returns:
        dict: Product details
    """
    title_elem = item.find("h2")
    price_elem = item.find("span", class_="a-price-whole")
    price_fraction = item.find("span", class_="a-price-fraction")
    link_elem = item.find("a", class_="a-link-normal")
    img_elem = item.find("img", class_="s-image")
    
    title = title_elem.get_text(strip=True) if title_elem else "No title found"
    price = price_elem.get_text(strip=True) if price_elem else "No price found"
    
    if price_fraction and price != "No price found":
        price += f".{price_fraction.get_text(strip=True)}"
    
    product_link = f"https://www.amazon.in{link_elem['href']}" if link_elem else "No link found"
    img_url = img_elem['src'] if img_elem else "No Image found"
    
    try:
        numerical_price = float(price.replace(",", "").strip())
    except ValueError:
        numerical_price = float('inf')
    
    return {
        "title": title,
        "price": price,
        "numerical_price": numerical_price,
        "link": product_link,
        "main_image": img_url
    }

def amazon_login(driver):
    """
    Automate Amazon login process.
    
    Args:
        driver (webdriver.Chrome): Selenium WebDriver
    
    Returns:
        bool: Login success status
    """
    try:
        email_input = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.NAME, "email"))
        )
        email_input.send_keys(AMAZON_EMAIL)
        
        continue_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "a-button-input"))
        )
        continue_button.click()
        
        password_input = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.NAME, "password"))
        )
        password_input.send_keys(AMAZON_PASSWORD)
        
        sign_in_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.ID, "signInSubmit"))
        )
        sign_in_button.click()
        
        if "ap/captcha" in driver.current_url:
            logger.warning("⚠️ CAPTCHA detected! Manual intervention required.")
            return False
        
        return True
    except Exception as e:
        logger.error(f"Login error: {e}")
        return False

def process_payment(driver):
    """
    Automate payment processing.
    
    Args:
        driver (webdriver.Chrome): Selenium WebDriver
    
    Returns:
        bool: Payment success status
    """
    try:
        iframe = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, '//iframe[@name="apx-secure-field-addCreditCardVerificationNumber"]'))
        )
        driver.switch_to.frame(iframe)
        
        cvv_input = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.TAG_NAME, 'input')))
        cvv_input.clear()
        cvv_input.send_keys(AMAZON_CVV)
        
        driver.switch_to.default_content()
        
        continue_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.NAME, 'ppw-widgetEvent:SetPaymentPlanSelectContinueEvent'))
        )
        continue_button.click()
        
        address_radio = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, '//input[@type="radio" and @name="submissionURL"]'))
        )
        if not address_radio.is_selected():
            address_radio.click()
        
        place_order_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.NAME, "placeYourOrder1"))
        )
        place_order_button.click()
        
        return True
    except Exception as e:
        logger.error(f"Order placement error: {str(e)}")
        return False

def navigate_to_orders_and_get_details(driver):
    """
    Navigate to orders page and retrieve order details.
    Only saves to database if order status is "Delivered".
    
    Args:
        driver (webdriver.Chrome): Selenium WebDriver
    
    Returns:
        dict: Order details including delivery date for delivered orders
    """
    try:
        driver.get("https://www.amazon.in")
        time.sleep(3)
        
        orders_link = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.ID, "nav-orders"))
        )
        orders_link.click()
        
        if "signin" in driver.current_url:
            if not amazon_login(driver):
                raise Exception("Login failed while checking order status")
            
            driver.get("https://www.amazon.in/gp/your-account/order-history")
        
        order_id = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "yohtmlc-order-id"))
        ).find_element(By.CSS_SELECTOR, "span[dir='ltr']").text.strip()
        
        title = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CLASS_NAME, "yohtmlc-product-title"))
        ).text.strip()
        
        delivery_status_element = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".a-size-medium.delivery-box__primary-text"))
        )
        delivery_status = delivery_status_element.text.strip()
        
        main_status = None
        delivery_date = None
        
        if "Delivered" in delivery_status:
            main_status = "Delivered"
            # Extract delivery date from status text (e.g., "Delivered 31 January")
            delivery_date = ' '.join(delivery_status.split()[1:])
        else:
            track_button = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "#a-autoid-2-announce"))
            )
            track_button.click()
            time.sleep(3)
            
            try:
                main_status = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "pt-status-main-status"))
                ).text.strip()
            except:
                main_status = "Status not available"
        
        order_data = {
            'order_id': order_id,
            'product_title': title,
            'current_status': main_status,
            'email': AMAZON_EMAIL,
            'success': True
        }
        
        if delivery_date:
            order_data['delivery_date'] = delivery_date
        
        # Only save to database if status is "Delivered"
        if main_status == "Delivered":
            save_to_db(order_collection, order_data, "order_id")
            order_data['saved_to_db'] = True
        else:
            order_data['saved_to_db'] = False
        
        return order_data
        
    except Exception as e:
        logger.error(f"Error checking order status: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'email': AMAZON_EMAIL
        }
    finally:
        if driver:
            driver.quit()
def login_amazon_and_continue(product_url):
    """
    Complete purchase flow for a product.
    
    Args:
        product_url (str): Product purchase URL
    
    Returns:
        tuple: Payment success status and order details
    """
    driver = create_driver(headless=False)
    try:
        driver.get(product_url)
        time.sleep(3)
        
        buy_now_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.ID, "buy-now-button"))
        )
        driver.execute_script("arguments[0].click();", buy_now_button)
        
        if not amazon_login(driver):
            logger.error("Login failed")
            return False, {"success": False, "error": "Login failed"}
        
        payment_success = process_payment(driver)
        logger.info(f"Payment processing {'successful' if payment_success else 'failed'}")
        
        # time.sleep(5)
        # order_details = navigate_to_orders_and_get_details(driver)
        
        return payment_success
    except Exception as e:
        logger.error(f"🚨 Unexpected error: {e}")
        return False, {"success": False, "error": str(e)}
    finally:
        driver.quit()

def find_lowest_price_item(items, department):
    """
    Find lowest-priced item matching department criteria.
    Only records price history when the price actually changes.
    
    Args:
        items (list): Product items
        department (str): Product department
    
    Returns:
        dict: Lowest-priced product details
    """
    lowest_price = float('inf')
    lowest_price_item = None
    lowest_price_details = None
    
    for item in items:
        if "Sponsored" in item.get_text():
            continue
        
        title_elem = item.find("h2")
        price_elem = item.find("span", class_="a-price-whole")
        price_fraction = item.find("span", class_="a-price-fraction")
        link_elem = item.find("a", class_="a-link-normal")
        img_elem = item.find("img", class_="s-image")
        
        title = title_elem.get_text(strip=True) if title_elem else "No title found"
        price = price_elem.get_text(strip=True) if price_elem else "No price found"
        
        if price_fraction and price != "No price found":
            price += f".{price_fraction.get_text(strip=True)}"
        
        product_link = f"https://www.amazon.in{link_elem['href']}" if link_elem else "No link found"
        img_url = img_elem['src'] if img_elem else "No Image found"
        
        try:
            numerical_price = float(price.replace(",", "").strip())
        except ValueError:
            continue
        
        if not is_valid_price(numerical_price, department):
            continue
        
        if numerical_price < lowest_price:
            lowest_price = numerical_price
            product_data = {
                "title": title,
                "price": price,
                "numerical_price": numerical_price,
                "link": product_link,
                "main_image": img_url
            }
            
            # Check existing product in database
            existing_product = product_collection.find_one({"title": title})
            if existing_product:
                old_price = existing_product.get("numerical_price", float('inf'))
                existing_history = existing_product.get("price_history", [])
                
                # Only add to history if price is different from the last recorded price
                if not existing_history or numerical_price != existing_history[-1].get("price"):
                    new_price_entry = {
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "price": numerical_price
                    }
                    
                    price_history = existing_history + [new_price_entry]
                    # Keep only last 10 entries
                    price_history = price_history[-10:]
                    product_data["price_history"] = price_history
                else:
                    # Keep existing history if price hasn't changed
                    product_data["price_history"] = existing_history
                
                # Add price comparison if price dropped
                if numerical_price < old_price:
                    price_difference = old_price - numerical_price
                    price_drop_percentage = (price_difference / old_price) * 100
                    product_data["price_drop"] = {
                        "old_price": old_price,
                        "difference": price_difference,
                        "percentage": round(price_drop_percentage, 2)
                    }
            else:
                # First time seeing this product
                product_data["price_history"] = [{
                    "price": numerical_price,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }]
            
            lowest_price_details = product_data
            lowest_price_item = product_data
    
    # Save lowest price item to database
    if lowest_price_details:
        save_to_db(product_collection, lowest_price_details, "title")
    
    return lowest_price_item

def is_valid_price(price, department):
    """
    Validate product price based on department.
    
    Args:
        price (float): Product price
        department (str): Product department
    
    Returns:
        bool: Price validity status
    """
    if department == 'electronics' and price < 5000:
        return False
    if department == 'computers' and price < 20000:
        return False
    return True
def update_stock_status(product):
    """
    Update product stock availability.
    
    Args:
        product (dict): Product details
    """
    driver = create_driver(headless=True)
    try:
        product_soup = get_soup(product['link'], driver)
        
        if not product_soup:
            product["stock_status"] = "Unknown"
            product["stock_quantity"] = "Unknown"
            return

        max_quantity = get_max_quantity_from_dropdown(product_soup)
        
        if max_quantity is None:
            product["stock_status"] = "Available"
            product["stock_quantity"] = 1
        else:
            product["stock_status"] = "Low Stock" if max_quantity <= 5 else "Available" if max_quantity > 0 else "Out of Stock"
            product["stock_quantity"] = max_quantity
    finally:
        driver.quit()

def get_max_quantity_from_dropdown(soup):
    """
    Extract maximum quantity from product dropdown.
    
    Args:
        soup (BeautifulSoup): Parsed product page
    
    Returns:
        int or None: Maximum available quantity
    """
    quantity_select = soup.find('select', {'id': 'quantity'})
    
    if quantity_select:
        options = quantity_select.find_all('option')
        max_quantity = max(int(option['value']) for option in options if option['value'].isdigit())
        return max_quantity
    
    return None
