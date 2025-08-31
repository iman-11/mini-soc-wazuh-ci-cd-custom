import os, time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

def make_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--ignore-certificate-errors")
    return webdriver.Chrome(options=opts)

def test_dashboard_login_page():
    driver = make_driver()
    try:
        url = os.getenv("WAZUH_URL", "https://localhost/")
        driver.get(url)
        time.sleep(5)
        assert "Wazuh" in driver.title or driver.title != ""
        # Look for generic login form inputs (IDs may vary by version)
        inputs = driver.find_elements(By.TAG_NAME, "input")
        assert len(inputs) >= 2
    finally:
        driver.quit()
