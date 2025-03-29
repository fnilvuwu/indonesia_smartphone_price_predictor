import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time
import random
import os
import shutil
import logging
from datetime import datetime
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraping.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def clean_price(price_text):
    """Clean price text to extract only the numeric value"""
    if not price_text:
        return None
    # Remove 'Rp' and replace dots with empty string (Indonesian format uses dots as thousand separators)
    price = price_text.replace('Rp', '').replace('.', '').strip()
    try:
        return int(price)
    except (ValueError, TypeError):
        return None

def extract_spec_value(text, pattern, unit=''):
    """Extract numeric value from specification text"""
    if not text:
        return None
    
    match = re.search(pattern, text)
    if match:
        try:
            return float(match.group(1).strip()) if '.' in match.group(1) else int(match.group(1).strip())
        except (ValueError, TypeError):
            return None
    return None

def create_backup(file_path):
    """Create a backup of the specified file"""
    if os.path.exists(file_path):
        # Create backups directory if it doesn't exist
        backup_dir = 'backups'
        if not os.path.exists(backup_dir):
            os.makedirs(backup_dir)
        
        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = os.path.basename(file_path)
        backup_name = f"{os.path.splitext(file_name)[0]}_{timestamp}{os.path.splitext(file_name)[1]}"
        backup_path = os.path.join(backup_dir, backup_name)
        
        # Copy the file to backup
        shutil.copy2(file_path, backup_path)
        logger.info(f"Backup created: {backup_path}")
        return backup_path
    return None

def save_data_to_csv(data, csv_filename, append=False):
    """Save data to CSV file, with option to append"""
    # Check if file exists to determine if we need to append
    file_exists = os.path.exists(csv_filename)
    
    # If file exists and we're not in append mode, create a backup
    if file_exists and not append:
        create_backup(csv_filename)
    
    mode = 'a' if append and file_exists else 'w'
    header = not (append and file_exists)
    
    # Create a DataFrame
    df = pd.DataFrame(data)
    
    # Save to CSV
    df.to_csv(csv_filename, mode=mode, header=header, index=False, encoding="utf-8")
    logger.info(f"Data {'appended to' if append and file_exists else 'saved to'} {csv_filename}")
    
    return df

def get_existing_phones(csv_filename):
    """Get list of phone names already in the CSV to avoid duplicates"""
    if os.path.exists(csv_filename):
        try:
            df = pd.read_csv(csv_filename)
            if 'Name' in df.columns:
                return set(df['Name'].tolist())
        except Exception as e:
            logger.error(f"Error reading existing CSV: {e}")
    return set()

def detect_layout(soup, page_number):
    """Detect the layout type based on page content and page number"""
    # Check for the newest layout first (seen on page 269+)
    # This layout has h2 headers with phone names and links with specs
    h2_headers = soup.find_all('h2')
    if h2_headers and len(h2_headers) > 5:  # Multiple h2 headers is a strong indicator
        for header in h2_headers:
            if "RAM" in header.text and "ROM" in header.text:
                return "newest"
    
    # Default to old layout for pages 1-201 and new layout for 202+
    default_layout = "new" if page_number >= 202 else "old"
    
    # Try to detect based on specific elements
    # New layout indicators
    new_layout_indicators = [
        soup.select('div[class*="productPanel"]'),
        soup.select('div.styles_productPanel__Tlvp6'),
        soup.select('div[class*="product"][class*="Panel"]')
    ]
    
    # Old layout indicators
    old_layout_indicators = [
        soup.find_all('div', class_='styles_productPanel__Tlvp6'),
        soup.find_all('div', class_='row')
    ]
    
    # Check for new layout indicators
    for indicator in new_layout_indicators:
        if indicator and len(indicator) > 0:
            return "new"
    
    # Check for old layout indicators
    for indicator in old_layout_indicators:
        if indicator and len(indicator) > 0:
            return "old"
    
    # If we couldn't detect, return the default based on page number
    return default_layout

def extract_product_data_new_layout(product):
    """Extract product data from the new layout (page 202+)"""
    try:
        # Extract product name
        name_element = product.find('h2', class_='styles_productName__fr99s')
        if not name_element:
            # Try alternative selectors for product name
            name_element = product.find('h2')
            if not name_element:
                name_element = product.find(['h2', 'h3', 'div'], class_=lambda c: c and ('name' in c.lower() or 'title' in c.lower()))
        
        if not name_element:
            return None
            
        name = name_element.text.strip()
        
        # Extract release year
        release_year = None
        year_div = product.find('div', class_='styles_yearReleased___jyCv')
        if year_div:
            year_span = year_div.find('span')
            if year_span:
                try:
                    release_year = int(year_span.text.strip())
                except (ValueError, TypeError):
                    pass
        
        # If year not found in the specific div, try to find it in any text containing a 4-digit year
        if not release_year:
            year_pattern = r'\b(20\d{2})\b'  # Pattern for years 2000-2099
            for element in product.find_all(text=True):
                match = re.search(year_pattern, element.strip())
                if match:
                    try:
                        release_year = int(match.group(1))
                        break
                    except (ValueError, TypeError):
                        pass
        
        # Extract price - try multiple approaches for the new layout
        price = None
        
        # Method 1: Look for price in any text containing 'Rp'
        for element in product.find_all(text=lambda text: text and 'Rp' in text):
            price_text = element.strip()
            price = clean_price(price_text)
            if price:
                break
        
        # Method 2: Look for elements with class containing 'price'
        if price is None:
            price_elements = product.find_all(class_=lambda c: c and 'price' in c.lower())
            for element in price_elements:
                if 'Rp' in element.text:
                    price = clean_price(element.text)
                    if price:
                        break
        
        # Extract specifications from the new layout
        specs_div = product.find('div', class_='styles_primarySpecsList__4s_rn')
        if not specs_div:
            # Try alternative selectors for specs
            specs_div = product.find('div', class_=lambda c: c and ('spec' in c.lower() or 'detail' in c.lower()))
        
        ram = None
        storage = None
        camera = None
        screen = None
        battery = None
        
        if specs_div:
            # In the new layout, specs are in divs with specific classes
            spec_items = specs_div.find_all('div', class_=lambda c: c and ('col-md-6' in c or 'spec' in c.lower()))
            
            for item in spec_items:
                spec_text = item.text.strip()
                
                # Check for RAM
                if 'GB' in spec_text and ('RAM' in spec_text.upper() or ram is None):
                    ram_match = re.search(r'(\d+)\s*GB', spec_text)
                    if ram_match:
                        ram = int(ram_match.group(1))
                
                # Check for storage
                if 'GB' in spec_text and ('ROM' in spec_text.upper() or 'STORAGE' in spec_text.upper() or storage is None):
                    storage_match = re.search(r'(\d+)\s*GB', spec_text)
                    if storage_match and 'RAM' not in spec_text.upper():  # Make sure it's not RAM
                        storage = int(storage_match.group(1))
                
                # Check for camera
                if 'MP' in spec_text and camera is None:
                    camera_match = re.search(r'(\d+)\s*MP', spec_text)
                    if camera_match:
                        camera = int(camera_match.group(1))
                
                # Check for screen size
                if 'inch' in spec_text and screen is None:
                    screen_match = re.search(r'([\d.]+)\s*inch', spec_text)
                    if screen_match:
                        screen = float(screen_match.group(1))
                
                # Check for battery
                if 'mAh' in spec_text and battery is None:
                    battery_match = re.search(r'(\d+)\s*mAh', spec_text)
                    if battery_match:
                        battery = int(battery_match.group(1))
        
        # Extract storage from the name if not found in specs
        if storage is None and 'ROM' in name:
            storage = extract_spec_value(name, r'ROM\s*(\d+)\s*GB')
        
        # Extract RAM from the name if not found in specs
        if ram is None and 'RAM' in name:
            ram = extract_spec_value(name, r'RAM\s*(\d+)\s*GB')
        
        # Create a dictionary for this phone
        phone_data = {
            'Name': name,
            'Price': price,
            'RAM': ram,
            'Storage': storage,
            'Camera': camera,
            'ScreenSize': screen,
            'Battery': battery,
            'ReleaseYear': release_year
        }
        
        return phone_data
    
    except Exception as e:
        logger.error(f"Error extracting product data from new layout: {e}")
        return None

def extract_product_data_old_layout(product):
    """Extract product data from the old layout (pages 1-201)"""
    try:
        # Extract product name
        name_element = product.find('h2', class_='styles_productName__fr99s')
        if not name_element:
            # Try alternative selectors for product name
            name_element = product.find('h2')
            if not name_element:
                name_element = product.find(['h2', 'h3', 'div'], class_=lambda c: c and ('name' in c.lower() or 'title' in c.lower()))
        
        if not name_element:
            return None
            
        name = name_element.text.strip()
        
        # Extract release year
        release_year = None
        year_div = product.find('div', class_='styles_yearReleased___jyCv')
        if year_div:
            year_span = year_div.find('span')
            if year_span:
                try:
                    release_year = int(year_span.text.strip())
                except (ValueError, TypeError):
                    pass
        
        # If year not found in the specific div, try to find it in any text containing a 4-digit year
        if not release_year:
            year_pattern = r'\b(20\d{2})\b'  # Pattern for years 2000-2099
            for element in product.find_all(text=True):
                match = re.search(year_pattern, element.strip())
                if match:
                    try:
                        release_year = int(match.group(1))
                        break
                    except (ValueError, TypeError):
                        pass
        
        # Extract price - try multiple approaches
        price = None
        
        # Method 1: Look for price in links
        price_links = product.find_all('a', href=lambda href: href and 'track/seller' in href)
        for link in price_links:
            price_text = link.text.strip()
            if 'Rp' in price_text:
                price = clean_price(price_text)
                break
        
        # Method 2: Look for price in any text containing 'Rp'
        if price is None:
            for element in product.find_all(text=lambda text: text and 'Rp' in text):
                price_text = element.strip()
                price = clean_price(price_text)
                if price:
                    break
        
        # Method 3: Check for table cells that might contain price
        if price is None:
            td_elements = product.find_all('td')
            for td in td_elements:
                if 'Rp' in td.text:
                    price = clean_price(td.text)
                    break
        
        # Method 4: Look for elements with class containing 'price'
        if price is None:
            price_elements = product.find_all(class_=lambda c: c and 'price' in c.lower())
            for element in price_elements:
                if 'Rp' in element.text:
                    price = clean_price(element.text)
                    if price:
                        break
        
        # Extract specifications
        specs_div = product.find('div', class_='styles_primarySpecsList__4s_rn')
        if not specs_div:
            # Try alternative selectors for specs
            specs_div = product.find('div', class_=lambda c: c and ('spec' in c.lower() or 'detail' in c.lower()))
        
        ram = None
        storage = None
        camera = None
        screen = None
        battery = None
        
        if specs_div:
            spec_items = specs_div.find_all('div', class_=lambda c: c and ('col-md-6' in c or 'spec' in c.lower()))
            
            for item in spec_items:
                spec_text = item.text.strip()
                
                if 'GB' in spec_text and ('RAM' in spec_text.upper() or ram is None):
                    ram = extract_spec_value(spec_text, r'(\d+)\s*GB')
                
                if 'GB' in spec_text and ('ROM' in spec_text.upper() or 'STORAGE' in spec_text.upper() or storage is None):
                    storage_match = re.search(r'(\d+)\s*GB', spec_text)
                    if storage_match and 'RAM' not in spec_text.upper():  # Make sure it's not RAM
                        storage = int(storage_match.group(1))
                
                if 'MP' in spec_text and camera is None:
                    camera = extract_spec_value(spec_text, r'(\d+)\s*MP')
                
                if 'inch' in spec_text and screen is None:
                    screen = extract_spec_value(spec_text, r'([\d.]+)\s*inch')
                
                if 'mAh' in spec_text and battery is None:
                    battery = extract_spec_value(spec_text, r'(\d+)\s*mAh')
        
        # Extract storage from the name if not found in specs
        if storage is None and 'ROM' in name:
            storage = extract_spec_value(name, r'ROM\s*(\d+)\s*GB')
        
        # Extract RAM from the name if not found in specs
        if ram is None and 'RAM' in name:
            ram = extract_spec_value(name, r'RAM\s*(\d+)\s*GB')
        
        # Create a dictionary for this phone
        phone_data = {
            'Name': name,
            'Price': price,
            'RAM': ram,
            'Storage': storage,
            'Camera': camera,
            'ScreenSize': screen,
            'Battery': battery,
            'ReleaseYear': release_year
        }
        
        return phone_data
    
    except Exception as e:
        logger.error(f"Error extracting product data from old layout: {e}")
        return None

def extract_product_data_newest_layout(header_element):
    """Extract product data from the newest layout (page 269+)"""
    try:
        # The name is in the h2 text
        name = header_element.text.strip()
        
        # Extract RAM and ROM from the name
        ram = None
        storage = None
        
        ram_match = re.search(r'RAM\s*(\d+(?:\.\d+)?)\s*GB', name)
        if ram_match:
            ram_value = ram_match.group(1)
            ram = float(ram_value) if '.' in ram_value else int(ram_value)
        
        storage_match = re.search(r'ROM\s*(\d+)\s*GB', name)
        if storage_match:
            storage = int(storage_match.group(1))
        
        # Find the next link after this header which contains the product details
        next_element = header_element.find_next('a')
        
        price = None
        camera = None
        screen = None
        battery = None
        release_year = None
        
        if next_element:
            # Extract specs from the link text
            link_text = next_element.text.strip()
            
            # Try to find price (Rp)
            price_match = re.search(r'Rp\s*([\d\.]+)', link_text)
            if price_match:
                price_text = price_match.group(0)
                price = clean_price(price_text)
            
            # Extract camera (MP)
            camera_match = re.search(r'(\d+)\s*MP', link_text)
            if camera_match:
                camera = int(camera_match.group(1))
            
            # Extract screen size (inch)
            screen_match = re.search(r'([\d\.]+)\s*inch', link_text)
            if screen_match:
                screen = float(screen_match.group(1))
            
            # Extract battery (mAh)
            battery_match = re.search(r'(\d+)\s*mAh', link_text)
            if battery_match:
                battery = int(battery_match.group(1))
            
            # Try to find release year in any text containing a 4-digit year
            year_pattern = r'\b(20\d{2})\b'  # Pattern for years 2000-2099
            year_match = re.search(year_pattern, link_text)
            if year_match:
                release_year = int(year_match.group(1))
        
        # Create a dictionary for this phone
        phone_data = {
            'Name': name,
            'Price': price,
            'RAM': ram,
            'Storage': storage,
            'Camera': camera,
            'ScreenSize': screen,
            'Battery': battery,
            'ReleaseYear': release_year
        }
        
        return phone_data
    
    except Exception as e:
        logger.error(f"Error extracting product data from newest layout: {e}")
        return None

def create_requests_session(max_retries=5, backoff_factor=0.3):
    """Create a requests session with retry functionality"""
    session = requests.Session()
    retry = Retry(
        total=max_retries,
        read=max_retries,
        connect=max_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def scrape_pricebook(url, csv_filename, backup_interval=5, max_retries=5, retry_delay=30, start_page=1, end_page=None):
    """Scrape smartphone data from Pricebook, saving data after each page"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # Create a session with retry functionality
    session = create_requests_session(max_retries=max_retries)
    
    page = start_page
    total_phones = 0
    empty_pages_count = 0
    max_empty_pages = 3  # Stop after 3 consecutive empty pages
    
    # Create initial backup if file exists
    if os.path.exists(csv_filename):
        create_backup(csv_filename)
        
    # Get existing phone names to avoid duplicates
    existing_phones = get_existing_phones(csv_filename)
    logger.info(f"Found {len(existing_phones)} existing phones in the CSV")
    
    while end_page is None or page <= end_page:
        page_url = f"{url}?page={page}" if page > 1 else url
        logger.info(f"Scraping page {page}: {page_url}")
        
        retry_count = 0
        success = False
        
        while not success and retry_count < max_retries:
            try:
                response = session.get(page_url, headers=headers, timeout=30)
                response.raise_for_status()  # Raise exception for HTTP errors
                success = True
            except requests.exceptions.RequestException as e:
                retry_count += 1
                if retry_count < max_retries:
                    wait_time = retry_delay * retry_count
                    logger.warning(f"Error accessing page {page}: {e}")
                    logger.info(f"Retrying in {wait_time} seconds... (Attempt {retry_count}/{max_retries})")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Failed to access page {page} after {max_retries} attempts: {e}")
                    # Don't break the entire loop, just move to the next page
                    page += 1
                    continue
        
        if not success:
            continue
        
        try:
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Detect layout type
            layout_type = detect_layout(soup, page)
            logger.info(f"Detected layout type for page {page}: {layout_type}")
            
            # List to store data from this page
            page_phones = []
            
            # Handle different layout types
            if layout_type == "newest":
                # For the newest layout (page 269+), find all h2 headers with phone names
                h2_headers = soup.find_all('h2')
                
                for header in h2_headers:
                    if "RAM" in header.text and "ROM" in header.text:
                        try:
                            phone_data = extract_product_data_newest_layout(header)
                            
                            if not phone_data or not phone_data['Name']:
                                continue
                            
                            # Skip if this phone is already in our dataset
                            if phone_data['Name'] in existing_phones:
                                logger.info(f"Skipping duplicate: {phone_data['Name']}")
                                continue
                            
                            # Add the phone even if price is None, we'll filter later if needed
                            page_phones.append(phone_data)
                            existing_phones.add(phone_data['Name'])  # Add to our tracking set
                            logger.info(f"Scraped: {phone_data['Name']} - RAM: {phone_data['RAM']} - Storage: {phone_data['Storage']}")
                            
                        except Exception as e:
                            logger.error(f"Error processing a product in newest layout: {e}")
                            continue
            else:
                # Find products based on layout type
                products = []
                
                if layout_type == "old":
                    # Try old layout selectors
                    products = soup.find_all('div', class_='styles_productPanel__Tlvp6')
                    
                    # If no products found, try alternative old layout
                    if not products:
                        products = soup.find_all('div', class_='row')
                else:  # new layout
                    # Try new layout selectors
                    products = soup.select('div.styles_productPanel__Tlvp6')
                    
                    # If still no products, try other selectors for the new layout
                    if not products:
                        products = soup.select('div[class*="productPanel"]')
                    
                    # If still no products, try to find any div that might contain product info
                    if not products:
                        # Look for divs that contain product information
                        potential_products = soup.find_all('div', class_=lambda c: c and ('product' in c.lower() or 'item' in c.lower()))
                        if potential_products:
                            products = potential_products
                
                # Last resort: try to find any div that might be a product container
                if not products:
                    # Look for divs with common product container classes or attributes
                    products = soup.find_all('div', class_=lambda c: c and any(term in c.lower() for term in ['product', 'item', 'card', 'listing']))
                
                if not products or len(products) == 0:
                    logger.warning(f"No products found on page {page}")
                    empty_pages_count += 1
                    if empty_pages_count >= max_empty_pages:
                        logger.info(f"Reached {max_empty_pages} consecutive empty pages. Stopping scraping.")
                        break
                    page += 1
                    continue
                
                # Reset empty pages counter since we found products
                empty_pages_count = 0
                
                for product in products:
                    try:
                        # Extract data based on the layout
                        if layout_type == "new":
                            phone_data = extract_product_data_new_layout(product)
                        else:
                            phone_data = extract_product_data_old_layout(product)
                        
                        if not phone_data or not phone_data['Name']:
                            continue
                        
                        # Skip if this phone is already in our dataset
                        if phone_data['Name'] in existing_phones:
                            logger.info(f"Skipping duplicate: {phone_data['Name']}")
                            continue
                        
                        if phone_data['Price'] is not None:  # Only add phones with valid prices
                            page_phones.append(phone_data)
                            existing_phones.add(phone_data['Name'])  # Add to our tracking set
                            logger.info(f"Scraped: {phone_data['Name']} - Price: {phone_data['Price']} - Year: {phone_data['ReleaseYear']}")
                        
                    except Exception as e:
                        logger.error(f"Error processing a product: {e}")
                        continue  # Continue with the next product
            
            # Save data from this page to CSV
            if page_phones:
                # Always append if the file exists
                append_mode = os.path.exists(csv_filename)
                save_data_to_csv(page_phones, csv_filename, append=append_mode)
                total_phones += len(page_phones)
                
                # Create backup at specified intervals
                if page % backup_interval == 0:
                    create_backup(csv_filename)
            else:
                logger.warning(f"No phones extracted from page {page}")
                empty_pages_count += 1
                if empty_pages_count >= max_empty_pages:
                    logger.info(f"Reached {max_empty_pages} consecutive empty pages with no data. Stopping scraping.")
                    break
            
            # Add a random delay between requests to be respectful to the server
            delay = random.uniform(1, 3)
            logger.info(f"Waiting {delay:.2f} seconds before next request...")
            time.sleep(delay)
            
            # Move to next page
            page += 1
            
        except Exception as e:
            logger.error(f"Error processing page {page}: {e}")
            # Create a backup in case of unexpected error
            if os.path.exists(csv_filename):
                create_backup(csv_filename)
            # Don't break, just move to the next page
            page += 1
    
    return total_phones

def main():
    # URL of the Pricebook smartphone page
    url = 'https://www.pricebook.co.id/smartphone'
    
    # CSV filename
    csv_filename = "smartphone_data.csv"
    
    # Parse command line arguments if needed
    import argparse
    parser = argparse.ArgumentParser(description='Scrape smartphone data from Pricebook')
    parser.add_argument('--start-page', type=int, default=1, help='Page to start scraping from')
    parser.add_argument('--end-page', type=int, default=None, help='Page to end scraping at (inclusive)')
    parser.add_argument('--backup-interval', type=int, default=5, help='Create backup every N pages')
    parser.add_argument('--max-retries', type=int, default=5, help='Maximum number of retries for failed requests')
    parser.add_argument('--retry-delay', type=int, default=30, help='Base delay between retries in seconds')
    
    args = parser.parse_args()
    
    logger.info("Starting web scraping of smartphone data from Pricebook")
    logger.info(f"Start page: {args.start_page}, End page: {args.end_page or 'until no more pages'}")
    
    # Scrape data from all pages
    total_phones = scrape_pricebook(
        url, 
        csv_filename, 
        backup_interval=args.backup_interval,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay,
        start_page=args.start_page,
        end_page=args.end_page
    )
    
    # Load the final dataset
    if os.path.exists(csv_filename):
        df = pd.read_csv(csv_filename)
        
        # Display summary
        logger.info(f"\nTotal smartphones collected: {len(df)}")
        logger.info("\nSample data:")
        logger.info(df.head())
        
        # Basic statistics
        logger.info("\nBasic statistics:")
        logger.info(df.describe())
        
        # Count missing values
        logger.info("\nMissing values per column:")
        logger.info(df.isnull().sum())
        
        # Save a summary report
        summary_file = "scraping_summary.txt"
        with open(summary_file, 'w') as f:
            f.write(f"Scraping Summary - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Total smartphones collected: {len(df)}\n\n")
            f.write("Sample data:\n")
            f.write(df.head().to_string() + "\n\n")
            f.write("Basic statistics:\n")
            f.write(df.describe().to_string() + "\n\n")
            f.write("Missing values per column:\n")
            f.write(df.isnull().sum().to_string() + "\n")
        
        logger.info(f"Summary report saved to {summary_file}")
    else:
        logger.error("No data was scraped. Check the website structure or connection.")

if __name__ == "__main__":
    main()
