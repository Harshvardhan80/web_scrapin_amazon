from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException
import time
import logging
from flask import Flask, request, jsonify
import os
from dotenv import load_dotenv
from database import product_collection, order_collection

# Load environment variables
load_dotenv()

# Retrieve credentials from environment variables
AMAZON_EMAIL = os.getenv("AMAZON_EMAIL")
AMAZON_PASSWORD = os.getenv("AMAZON_PASSWORD")
AMAZON_CVV = os.getenv("AMAZON_CVV") 

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_department_id(query):
    # Map common products to their department IDs
    product_departments = {
        'iphone': 'electronics',
        'samsung': 'electronics',
        'macbook': 'computers',
        'laptop': 'computers',
        'ipad': 'electronics',
        # Add more mappings as needed
    }
    
    query_lower = query.lower()
    for key, department in product_departments.items():
        if key in query_lower:
            return department
    return 'all'

def create_driver(headless=True):
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    
    # Cloud-friendly Chrome options
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--remote-debugging-port=9222")
    
    # Custom user agent
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

    try:
        # Try to find Chrome binary
        chrome_binary = None
        possible_paths = [
            "/usr/bin/google-chrome-stable",
            "/usr/bin/google-chrome",
            "google-chrome",  # Search in PATH
        ]
        
        for path in possible_paths:
            try:
                if path.startswith("/"):
                    if os.path.exists(path):
                        chrome_binary = path
                        break
                else:
                    # Try to find in PATH
                    import subprocess
                    result = subprocess.run(['which', path], capture_output=True, text=True)
                    if result.returncode == 0:
                        chrome_binary = result.stdout.strip()
                        break
            except Exception as e:
                logger.debug(f"Failed to check path {path}: {e}")
                continue
        
        if chrome_binary:
            options.binary_location = chrome_binary
            logger.info(f"Using Chrome binary at: {chrome_binary}")
        else:
            logger.warning("Chrome binary not found in standard locations, letting ChromeDriver decide")
        
        # Create service with specific chrome version
        try:
            chrome_version = subprocess.check_output(['google-chrome', '--version']).decode().strip().split()[-1]
            logger.info(f"Detected Chrome version: {chrome_version}")
            service = Service(ChromeDriverManager(version=chrome_version).install())
        except Exception as e:
            logger.warning(f"Failed to get Chrome version, using latest: {e}")
            service = Service(ChromeDriverManager().install())
        
        # Create driver with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                driver = webdriver.Chrome(service=service, options=options)
                logger.info("Successfully created Chrome driver")
                return driver
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                time.sleep(2 * (attempt + 1))  # Exponential backoff
                
    except Exception as e:
        error_msg = f"Failed to create Chrome driver: {str(e)}"
        logger.error(error_msg)
        raise Exception(error_msg)

def get_soup(url, driver):
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
    try:
        existing_record = collection.find_one({key: data[key]})
        if existing_record:
            collection.update_one({key: data[key]}, {"$set": data})
        else:
            collection.insert_one(data)
    except Exception as e:
        logger.error(f"Error saving to database: {e}")

def extract_product_details(item):
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
    try:
        iframe = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, '//iframe[@name="apx-secure-field-addCreditCardVerificationNumber"]'))
        )
        driver.switch_to.frame(iframe)

        cvv_input = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.TAG_NAME, 'input')))
        cvv_input.clear()
        cvv_input.send_keys(AMAZON_CVV)  # Use CVV from .env
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

        delivery_status = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".a-size-medium.delivery-box__primary-text"))
        ).text.strip()

        if "Delivered" in delivery_status:
            main_status = "Delivered"
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

        save_to_db(order_collection, order_data, "order_id")
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

        time.sleep(5)
        order_details = navigate_to_orders_and_get_details(driver)

        return payment_success, order_details

    except Exception as e:
        logger.error(f"🚨 Unexpected error: {e}")
        return False, {"success": False, "error": str(e)}

    finally:
        driver.quit()

def find_lowest_price_item(items, department):
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
            lowest_price_details = product_data
            lowest_price_item = product_data

    # Only save to database if we found a valid lowest price item
    if lowest_price_details:
        save_to_db(product_collection, lowest_price_details, "title")

    return lowest_price_item

def is_valid_price(price, department):
    if department == 'electronics' and price < 5000:
        return False
    if department == 'computers' and price < 20000:
        return False
    return True

def update_stock_status(product):
    driver = create_driver(headless=True)  # Create a driver instance
    try:
        product_soup = get_soup(product['link'], driver)  # Pass the driver to get_soup
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
        driver.quit()  # Ensure the driver is closed after use

def get_max_quantity_from_dropdown(soup):
    quantity_select = soup.find('select', {'id': 'quantity'})
    if quantity_select:
        options = quantity_select.find_all('option')
        max_quantity = max(int(option['value']) for option in options if option['value'].isdigit())
        return max_quantity
    return None