import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException
import time
import random
import logging
import json
from flask import Flask, request, jsonify
import os
import re

app = Flask(__name__)

# Predefined Amazon login credentials
AMAZON_EMAIL = "ashukumarsharma8@gmail.com"
AMAZON_PASSWORD = "ashu@@001"

def get_soup(url):
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.headless = True

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get(url)
        time.sleep(5)
        page_source = driver.page_source

        if "Enter the characters you see below" in page_source:
            print("⚠️ Amazon CAPTCHA detected. Solve it manually and continue.")
            return None

        return BeautifulSoup(page_source, "html.parser")
    except Exception as e:
        print(f"Error fetching page: {e}")
        return None
    finally:
        driver.quit()

def extract_product_details(item):
    # Basic elements
    title_elem = item.find("h2")
    price_elem = item.find("span", class_="a-price-whole")
    price_fraction = item.find("span", class_="a-price-fraction")
    link_elem = item.find("a", class_="a-link-normal")
    img_elem = item.find("img", class_="s-image")
    
    # Get product category
    category_elem = item.find("div", class_="a-row a-size-base a-color-secondary")
    
    # Extract basic details
    title = title_elem.get_text(strip=True) if title_elem else "No title found"
    price = price_elem.get_text(strip=True) if price_elem else "No price found"
    if price_fraction:
        price += f".{price_fraction.get_text(strip=True)}"
    
    product_link = f"https://www.amazon.in{link_elem['href']}" if link_elem else "No link found"
    img_url = img_elem['src'] if img_elem else "No Image found"
    category = category_elem.get_text(strip=True) if category_elem else ""
    
    try:
        numerical_price = float(price.replace(",", "").strip())
    except ValueError:
        numerical_price = float('inf')
    
    return {
        "title": title,
        "price": price,
        "numerical_price": numerical_price,
        "link": product_link,
        "main_image": img_url,
        "category": category
    }

def get_max_quantity_from_dropdown(soup):
    quantity_select = soup.find('select', {'id': 'quantity'})
    if quantity_select:
        options = quantity_select.find_all('option')
        max_quantity = max(int(option['value']) for option in options if option['value'].isdigit())
        return max_quantity
    return None  # Return None if no quantity is provided


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
def create_amazon_driver():
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--start-maximized")
    options.add_argument("--disable-popup-blocking")
    options.headless = False

    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def amazon_login(driver):
    try:
        # Email input
        email_input = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.NAME, "email"))
        )
        email_input.send_keys(AMAZON_EMAIL)
        
        # Continue button
        continue_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.CLASS_NAME, "a-button-input"))
        )
        continue_button.click()

        # Password input
        password_input = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.NAME, "password"))
        )
        password_input.send_keys(AMAZON_PASSWORD)
        
        # Sign in button
        sign_in_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.ID, "signInSubmit"))
        )
        sign_in_button.click()

        # Check for CAPTCHA
        if "ap/captcha" in driver.current_url:
            print("⚠️ CAPTCHA detected! Manual intervention required.")
            return False

        return True
    except Exception as e:
        print(f"Login error: {e}")
        return False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def wait_for_otp_screen(driver, timeout=30):
    """Wait for and verify OTP input screen presence"""
    try:
        # Common OTP frame/element identifiers on Amazon
        otp_identifiers = [
            (By.XPATH, "//input[contains(@name, 'otpValue')]"),
            (By.XPATH, "//input[contains(@name, 'code')]"),
            (By.XPATH, "//input[contains(@id, 'otp')]"),
            (By.XPATH, "//input[contains(@placeholder, 'OTP')]"),
            (By.XPATH, "//input[contains(@placeholder, 'Enter code')]")
        ]
        
        logger.info("Waiting for OTP screen...")
        for identifier in otp_identifiers:
            try:
                element = WebDriverWait(driver, timeout).until(
                    EC.presence_of_element_located(identifier)
                )
                if element:
                    logger.info("OTP input field found")
                    return element
            except:
                continue
                
        raise TimeoutException("OTP input field not found")
        
    except Exception as e:
        logger.error(f"Error waiting for OTP screen: {str(e)}")
        return None

def process_payment(driver):
    """
    Process payment with OTP verification handling
    Returns: bool - Success status
    """
    try:
        # Switch to iframe for CVV input
        logger.info("Attempting to locate CVV iframe...")
        iframe = WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.XPATH, '//iframe[@name="apx-secure-field-addCreditCardVerificationNumber"]'))
        )
        driver.switch_to.frame(iframe)
        
        try:
            cvv_input = WebDriverWait(driver, 20).until(EC.element_to_be_clickable((By.TAG_NAME, 'input')))
            cvv_input.clear()
            cvv_input.send_keys("399")
            logger.info("CVV entered successfully")
        finally:
            driver.switch_to.default_content()

        # Click 'Use this payment method'
        logger.info("Selecting payment method...")
        continue_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.NAME, 'ppw-widgetEvent:SetPaymentPlanSelectContinueEvent'))
        )
        continue_button.click()

        # Address selection
        logger.info("Selecting delivery address...")
        try:
            address_radio = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.XPATH, '//input[@type="radio" and @name="submissionURL"]'))
            )
            if not address_radio.is_selected():
                address_radio.click()
        except TimeoutException:
            logger.warning("Address selection elements not found, continuing...")

        # Place Order and Pay
        def try_click_place_order():
            methods = [
                (By.NAME, "placeYourOrder1"),
                (By.XPATH, '//input[@name="placeYourOrder1"]'),
                (By.XPATH, '//span[@id="submitOrderButtonId"]'),
                (By.ID, "submitOrderButtonId")
            ]
            
            for method in methods:
                try:
                    logger.info(f"Attempting to click place order using {method}")
                    button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(method))
                    button.click()
                    return True
                except Exception:
                    continue
            
            return False

        if not try_click_place_order():
            logger.error("Failed to click 'Place Your Order and Pay' button")
            return False

        logger.info("Order placement successful, waiting for OTP verification...")
        
        # Wait for OTP screen
        otp_input = wait_for_otp_screen(driver)
        if not otp_input:
            logger.error("Failed to locate OTP input field")
            return False
            
        # Here you can either:
        # 1. Wait for manual OTP input
        logger.info("OTP screen detected. Waiting for manual OTP input...")
        WebDriverWait(driver, 180).until(
            lambda d: otp_input.get_attribute('value') and len(otp_input.get_attribute('value')) >= 4
        )
        
        # Or 2. Handle automatic OTP input if you have a way to get the OTP
        # otp_input.send_keys(your_otp)
        
        # Look for and click submit button
        submit_buttons = [
            (By.XPATH, "//button[contains(text(), 'Submit')]"),
            (By.XPATH, "//input[@type='submit']"),
            (By.XPATH, "//button[contains(@class, 'submit')]"),
            (By.XPATH, "//button[contains(text(), 'Verify')]")
        ]
        
        for button in submit_buttons:
            try:
                submit = WebDriverWait(driver, 10).until(EC.element_to_be_clickable(button))
                submit.click()
                logger.info("OTP submitted successfully")
                break
            except:
                continue

        return True

    except Exception as e:
        logger.error(f"Order placement error: {str(e)}")
        return False

def login_amazon_and_continue(product_url):
    driver = create_amazon_driver()

    try:
        driver.get(product_url)
        time.sleep(random.uniform(3, 6))

        # Click 'Buy Now' Button
        buy_now_button = WebDriverWait(driver, 30).until(
            EC.element_to_be_clickable((By.ID, "buy-now-button"))
        )
        driver.execute_script("arguments[0].click();", buy_now_button)

        # Login Process
        if not amazon_login(driver):
            return None

        # Process Payment
        if not process_payment(driver):
            return None

        return driver.current_url
    
    except Exception as e:
        print(f"🚨 Unexpected error: {e}")
        return None
    
    finally:
        driver.quit()

@app.route('/scrape_amazon', methods=['POST'])
def scrape_amazon_endpoint():
    data = request.json
    if not data or 'query' not in data:
        return jsonify({"error": "Missing required 'query' parameter"}), 400
    
    query = data['query']
    department = get_department_id(query)
    
    try:
        # Build search URL with department and refinements
        base_url = f"https://www.amazon.in/s?k={query}"
        if department != 'all':
            base_url += f"&i={department}"
            
        # Add refinements to exclude accessories
        search_url = f"{base_url}&rh=n%3A976419031%2Cp_n_format_browse-bin%3A19150304031"
        
        search_soup = get_soup(search_url)
        
        if not search_soup:
            return jsonify({"error": "Failed to fetch search results"}), 500
        
        # Find the main category results
        items = search_soup.find_all("div", class_="s-result-item")
        lowest_price = float('inf')
        lowest_price_item = None
        
        for item in items:
            product_details = extract_product_details(item)
            
            # Skip sponsored products
            if "Sponsored" in item.get_text():
                continue
                
            # Skip if price is suspiciously low for the category
            if department == 'electronics' and product_details["numerical_price"] < 5000:
                continue
            elif department == 'computers' and product_details["numerical_price"] < 20000:
                continue
            
            if product_details["numerical_price"] < lowest_price:
                lowest_price = product_details["numerical_price"]
                lowest_price_item = product_details
        
        if not lowest_price_item:
            # Try without refinements if no results found
            search_url = base_url
            search_soup = get_soup(search_url)
            items = search_soup.find_all("div", class_="s-result-item")
            
            for item in items:
                product_details = extract_product_details(item)
                if product_details["numerical_price"] < lowest_price:
                    lowest_price = product_details["numerical_price"]
                    lowest_price_item = product_details
        
        if lowest_price_item:
            # Visit the product page to get stock quantity
            product_soup = get_soup(lowest_price_item['link'])
            if product_soup:
                max_quantity = get_max_quantity_from_dropdown(product_soup)
                
                if max_quantity is None:
                    # If no quantity info is available, assume minimum stock and click "buy"
                    lowest_price_item["stock_status"] = "Available"
                    lowest_price_item["stock_quantity"] = 1  # Assume the minimum stock
                else:
                    if max_quantity > 0:
                        if max_quantity <= 5:
                            stock_status = "Low Stock"
                        else:
                            stock_status = "Available"
                    else:
                        stock_status = "Out of Stock"
                    lowest_price_item["stock_status"] = stock_status
                    lowest_price_item["stock_quantity"] = max_quantity
        
        next_page = login_amazon_and_continue(lowest_price_item['link']) if lowest_price_item else None
        
        return jsonify({
            "lowest_price_product": lowest_price_item,
            "next_page": next_page
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)