import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import json
from flask import Flask, request, jsonify
import os

app = Flask(__name__)

# Predefined Amazon login credentials
AMAZON_EMAIL = "hv9828378@gmail.com"
AMAZON_PASSWORD = "061823609"

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
    title_elem = item.find("h2")
    price_elem = item.find("span", class_="a-price-whole")
    price_fraction = item.find("span", class_="a-price-fraction")
    link_elem = item.find("a", class_="a-link-normal")

    title = title_elem.get_text(strip=True) if title_elem else "No title found"
    price = price_elem.get_text(strip=True) if price_elem else "No price found"
    if price_fraction:
        price += f".{price_fraction.get_text(strip=True)}"

    product_link = f"https://www.amazon.in{link_elem['href']}" if link_elem else "No link found"

    try:
        numerical_price = float(price.replace(",", "").strip())
    except ValueError:
        numerical_price = float('inf')

    return title, price, product_link, numerical_price

def login_amazon_and_continue(product_url):
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.headless = True

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    try:
        driver.get(product_url)
        time.sleep(3)

        def find_and_click(by, value):
            try:
                button = driver.find_element(by, value)
                button.click()
                time.sleep(2)
                return True
            except Exception:
                return False

        if not find_and_click(By.ID, "buy-now-button"):
            print("Error clicking 'Buy Now' button.")
            return None

        try:
            email_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "ap_email")))
            email_input.send_keys(AMAZON_EMAIL)
            find_and_click(By.ID, "continue")

            password_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "ap_password")))
            password_input.send_keys(AMAZON_PASSWORD)
            find_and_click(By.ID, "signInSubmit")
        except Exception as e:
            print("Error entering login details:", e)
            return None

        time.sleep(5)
        return driver.current_url
    
    except Exception as e:
        print(f"Unexpected error: {e}")
        return None
    
    finally:
        driver.quit()

@app.route('/scrape_amazon', methods=['POST'])
def scrape_amazon_endpoint():
    data = request.json
    if not data or 'query' not in data:
        return jsonify({"error": "Missing required 'query' parameter"}), 400
    
    query = data['query']
    
    try:
        search_url = f"https://www.amazon.in/s?k={query}"
        soup = get_soup(search_url)
        
        if not soup:
            return jsonify({"error": "Failed to fetch search results"}), 500
        
        items = soup.find_all("div", class_="s-result-item")
        
        lowest_price = float('inf')
        lowest_price_item = {"title": "No title", "price": "N/A", "link": "N/A", "in_stock": False}
        
        for item in items:
            title, price, product_link, numerical_price = extract_product_details(item)
            if numerical_price < lowest_price:
                lowest_price = numerical_price
                lowest_price_item = {
                    "title": title, 
                    "price": price, 
                    "link": product_link, 
                    "in_stock": True
                }
        
        next_page = login_amazon_and_continue(lowest_price_item['link'])
        
        return jsonify({
            "product": lowest_price_item,
            "next_page": next_page
        }), 200
    
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)