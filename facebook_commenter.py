# facebook_commenter.py
import os
import csv
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import time
import pyotp
import zipfile
import sys
import shutil
import random
from datetime import datetime, timedelta

class DelayConfig:
    def __init__(self):
        self.between_comments = (1, 5)
        self.between_sessions = (3, 7)
        self.between_actions = (1, 3)
        self.comments_per_session = 5

    def get_comment_delay(self):
        return random.uniform(*self.between_comments)

    def get_session_delay(self):
        return random.uniform(*self.between_sessions)

    def get_action_delay(self):
        return random.uniform(*self.between_actions)

class FacebookCommenter:
    def __init__(self, csv_path, log_callback=None, progress_callback=None, status_callback=None, stats_callback=None):
        self.data = None
        self.csv_path = csv_path
        self.log_callback = log_callback
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.stats_callback = stats_callback
        self.profiles_dir = os.path.expanduser('~/fb_chrome_profiles')
        self.is_running = True
        self.stats = {"success": 0, "failed": 0, "skipped": 0}
        self.delays = DelayConfig()
        
        if not os.path.exists(self.profiles_dir):
            os.makedirs(self.profiles_dir)
    
    def log(self, message):
        print(message)
        if self.log_callback:
            self.log_callback(message)
    
    def random_delay(self, action_type="action"):
        if action_type == "comment":
            delay = self.delays.get_comment_delay()
            self.log(f"Waiting {delay:.1f} seconds before next comment...")
        elif action_type == "session":
            delay = self.delays.get_session_delay()
            self.log(f"Taking a break for {delay/60:.1f} minutes...")
        else:
            delay = self.delays.get_action_delay()
        time.sleep(delay)
    
    def upload_image(self, driver, image_path):
        try:
            # Create hidden file input
            driver.execute_script("""
                const input = document.createElement('input');
                input.type = 'file';
                input.id = 'hidden-file-input';
                input.style.display = 'none';
                document.body.appendChild(input);
            """)
            
            # Find and use the hidden input
            file_input = driver.find_element(By.ID, "hidden-file-input")
            file_input.send_keys(os.path.abspath(image_path))
            
            # Wait for image preview
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "img[alt*='photo'], div[role='img']"))
            )
            
            # Cleanup
            driver.execute_script("""
                const input = document.getElementById('hidden-file-input');
                if (input) input.remove();
            """)
            
            return True
        except Exception as e:
            self.log(f"Failed to upload image: {str(e)}")
            return False
            
    def update_progress(self, value):
        if self.progress_callback:
            self.progress_callback(value)
            
    def update_status(self, row_id, status):
        if self.status_callback:
            self.status_callback(row_id, status)
            
    def update_stats(self):
        if self.stats_callback:
            self.stats_callback(self.stats)

    def get_chromedriver_path(self):
        chromedriver_path = '/opt/homebrew/Caskroom/chromedriver/131.0.6778.204/chromedriver-mac-arm64/chromedriver'
        print(f"Using ChromeDriver at: {chromedriver_path}")
        
        if not os.path.exists(chromedriver_path):
            print(f"Warning: ChromeDriver not found at {chromedriver_path}")
            chromedriver_path = '/opt/homebrew/bin/chromedriver'
            print(f"Trying fallback path: {chromedriver_path}")

        try:
            os.chmod(chromedriver_path, 0o755)
            print("Set ChromeDriver permissions")
        except Exception as e:
            print(f"Warning: Could not set ChromeDriver permissions: {e}")

        return chromedriver_path

    def read_csv_data(self):
        try:
            with open(self.csv_path, 'r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file)
                data = list(reader)
                self.log(f"Found {len(data)} accounts in CSV file")
                return data
        except Exception as e:
            self.log(f"Error reading CSV file: {str(e)}")
            return []

    def create_proxy_extension(self, proxy_host, proxy_port, proxy_username, proxy_password):
        manifest_json = """
        {
            "version": "1.0.0",
            "manifest_version": 2,
            "name": "Chrome Proxy",
            "permissions": [
                "proxy",
                "tabs",
                "unlimitedStorage",
                "storage",
                "<all_urls>",
                "webRequest",
                "webRequestBlocking"
            ],
            "background": {
                "scripts": ["background.js"]
            },
            "minimum_chrome_version": "22.0.0"
        }
        """

        background_js = """
        var config = {
            mode: "fixed_servers",
            rules: {
                singleProxy: {
                    scheme: "http",
                    host: "%s",
                    port: %s
                },
                bypassList: []
            }
        };

        chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});

        function callbackFn(details) {
            return {
                authCredentials: {
                    username: "%s",
                    password: "%s"
                }
            };
        }

        chrome.webRequest.onAuthRequired.addListener(
            callbackFn,
            {urls: ["<all_urls>"]},
            ['blocking']
        );
        """ % (proxy_host, proxy_port, proxy_username, proxy_password)

        extension_dir = os.path.join(self.profiles_dir, "proxy_extension")
        if not os.path.exists(extension_dir):
            os.makedirs(extension_dir)

        with open(os.path.join(extension_dir, "manifest.json"), 'w') as f:
            f.write(manifest_json)
        with open(os.path.join(extension_dir, "background.js"), 'w') as f:
            f.write(background_js)

        extension_path = os.path.join(self.profiles_dir, "proxy_auth.zip")
        with zipfile.ZipFile(extension_path, 'w') as zp:
            zp.write(os.path.join(extension_dir, "manifest.json"), "manifest.json")
            zp.write(os.path.join(extension_dir, "background.js"), "background.js")

        return extension_path

    def setup_chrome_profile(self, profile_name, proxy=None):
        try:
            options = webdriver.ChromeOptions()
            
            if proxy:
                parts = proxy.split(':')
                if len(parts) == 4:
                    proxy_host, proxy_port, proxy_username, proxy_password = parts
                    
                    print(f"Setting up proxy:")
                    print(f"Host: {proxy_host}")
                    print(f"Port: {proxy_port}")
                    print(f"Username: {proxy_username}")
                    
                    proxy_extension = self.create_proxy_extension(
                        proxy_host, proxy_port, proxy_username, proxy_password
                    )
                    options.add_extension(proxy_extension)
                    
                    options.add_argument(f'--proxy-server=http://{proxy_host}:{proxy_port}')

            profile_path = os.path.join(self.profiles_dir, profile_name)
            options.add_argument(f'user-data-dir={profile_path}')
            
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--ignore-certificate-errors')
            options.add_argument('--ignore-ssl-errors')
            
            chromedriver_path = self.get_chromedriver_path()
            print(f"Creating Chrome service with driver at: {chromedriver_path}")
            service = Service(executable_path=chromedriver_path)
            driver = webdriver.Chrome(service=service, options=options)
            return driver
            
        except Exception as e:
            print(f"Error setting up Chrome profile: {str(e)}")
            raise

    def login_facebook(self, driver, email, password, totp_secret):
        print(f"Checking login status for: {email}")
        driver.get('https://www.facebook.com')
        time.sleep(5)
        
        try:
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[aria-label='Facebook']")))
                print("Already logged in, proceeding...")
                return True
            except TimeoutException:
                print("Not logged in, attempting login...")
                
                email_field = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "email"))
                )
                email_field.send_keys(email)
                
                password_field = driver.find_element(By.ID, "pass")
                password_field.send_keys(password)
                
                time.sleep(2)
                
                login_button = driver.find_element(By.NAME, "login")
                login_button.click()
                
                try:
                    totp = pyotp.TOTP(totp_secret)
                    code_field = WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.NAME, "approvals_code"))
                    )
                    code_field.send_keys(totp.now())
                    
                    submit_2fa = driver.find_element(By.ID, "checkpointSubmitButton")
                    submit_2fa.click()
                    
                    print(f"2FA code submitted for {email}")
                    time.sleep(3)
                except TimeoutException:
                    print(f"No 2FA prompt appeared for {email}")
                    pass
                    
        except Exception as e:
            print(f"Login process failed for {email}: {str(e)}")
            return False
        
        return True

    def post_comment(self, driver, post_url, comment, reply_to=None, image_path=None):
        if not comment:
            self.log("No comment provided, skipping comment posting")
            return False
                
        self.log(f"Attempting to post comment{' with image' if image_path else ''}")
        driver.get(post_url)
        self.random_delay()
        
        try:
            if reply_to and reply_to.strip():
                self.log(f"Looking for comment by {reply_to}...")
                # Scroll down a few times to load more comments
                for _ in range(3):
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    self.random_delay("action")
                
                # Find all comments
                comments = WebDriverWait(driver, 10).until(
                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, "div[role='article']"))
                )
                
                self.log(f"Found {len(comments)} comments, searching for {reply_to}")
                found_comment = False
                
                # Look through each comment for the specified name
                for comment_elem in comments:
                    try:
                        # Try to find the commenter's name within this comment
                        name_elements = comment_elem.find_elements(By.CSS_SELECTOR, "a.x1i10hfl")
                        for name_elem in name_elements:
                            if reply_to.lower() in name_elem.text.lower():
                                self.log(f"Found {reply_to}'s comment")
                                # Find the reply button
                                reply_buttons = comment_elem.find_elements(
                                    By.CSS_SELECTOR, 
                                    "div[role='button']"
                                )
                                for button in reply_buttons:
                                    if "reply" in button.get_attribute("innerHTML").lower():
                                        self.log("Found reply button, clicking...")
                                        driver.execute_script("arguments[0].click();", button)
                                        found_comment = True
                                        self.random_delay("action")
                                        break
                                if found_comment:
                                    break
                    except Exception as e:
                        self.log(f"Error processing comment: {str(e)}")
                        continue
                    
                    if found_comment:
                        break
                
                if not found_comment:
                    raise Exception(f"Could not find comment by {reply_to}")

            # Find comment box
            self.log("Looking for comment box...")
            selectors = [
                "div[contenteditable='true']",
                "[aria-label='Write a comment']",
                "[aria-label='Write a Comment']",
                "div[role='textbox']",
                "div.xzsf02u",
                "div.x1cy8zhl"
            ]
            
            comment_box = None
            for selector in selectors:
                try:
                    elements = WebDriverWait(driver, 5).until(
                        EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector))
                    )
                    self.log(f"Found {len(elements)} potential comment boxes with selector: {selector}")
                    for element in elements:
                        if element.is_displayed() and element.is_enabled():
                            comment_box = element
                            self.log("Found usable comment box")
                            break
                    if comment_box:
                        break
                except:
                    continue
            
            if not comment_box:
                raise Exception("Could not find comment box")

            # Click comment box
            self.log("Clicking comment box...")
            driver.execute_script("arguments[0].click();", comment_box)
            self.random_delay("action")

            # Handle image upload if present
            if image_path:
                self.log(f"Attempting to upload image: {image_path}")
                try:
                    # Find and click the photo button
                    photo_button = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "[aria-label='Attach a photo or video']"))
                    )
                    driver.execute_script("arguments[0].click();", photo_button)
                    self.random_delay("action")
                    
                    # Wait for and find the file input
                    file_input = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='file']"))
                    )
                    
                    # Send the file path
                    file_input.send_keys(os.path.abspath(image_path))
                    self.log("Sent image path, waiting for upload...")
                    
                    # Wait for image to be uploaded (look for preview)
                    WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "[role='img'], img[alt*='photo']"))
                    )
                    self.log("Image upload confirmed")
                    self.random_delay("action")
                    
                except Exception as e:
                    self.log(f"Failed to upload image: {str(e)}")
            
            # Type the comment
            self.log("Attempting to input comment text...")
            try:
                comment_box.clear()
                comment_box.send_keys(comment)
                self.random_delay("action")
                self.log("Sending return key...")
                comment_box.send_keys(Keys.RETURN)
            except Exception as e:
                self.log(f"Direct input failed, trying alternative methods: {str(e)}")
                try:
                    actions = ActionChains(driver)
                    actions.move_to_element(comment_box)
                    actions.click()
                    actions.send_keys(comment)
                    actions.send_keys(Keys.RETURN)
                    actions.perform()
                except Exception as e2:
                    self.log(f"ActionChains failed, trying JavaScript: {str(e2)}")
                    try:
                        driver.execute_script(f'arguments[0].textContent = "{comment}";', comment_box)
                        comment_box.send_keys(Keys.RETURN)
                    except Exception as e3:
                        self.log(f"JavaScript input failed: {str(e3)}")
                        raise Exception("All comment input methods failed")
            
            # Verify comment was posted
            self.random_delay()
            self.log("Verifying comment was posted...")
            try:
                comments = driver.find_elements(By.CSS_SELECTOR, "div[role='article']")
                self.log(f"Found {len(comments)} comments on page")
                for c in comments:
                    has_comment = comment in c.text
                    has_image = len(c.find_elements(By.CSS_SELECTOR, "img[alt*='photo'], div[role='img']")) > 0
                    if has_comment or has_image:
                        self.log("Comment/image found on page - posting successful")
                        return True
                raise Exception("Comment/image not found on page after posting")
            except Exception as e:
                self.log(f"Verification failed: {str(e)}")
                raise
                
        except Exception as e:
            self.log(f"Failed to post comment: {str(e)}")
            return False
            
    def stop(self):
        self.is_running = False
        
    def run(self):
        if not self.data:
            self.data = self.read_csv_data()
        if not self.data:
            self.log("No data found in CSV file. Exiting...")
            return

        total_accounts = len(self.data)
        comments_in_session = 0

        for index, row in enumerate(self.data):
            if not self.is_running:
                self.log("Bot stopped by user")
                break
                
            try:
                # Check for session break
                if comments_in_session >= self.delays.comments_per_session:
                    self.log("Taking a break between sessions...")
                    self.random_delay("session")
                    comments_in_session = 0

                email = row['email'].strip()
                comment = row.get('comment', '').strip()
                reply_to = row.get('reply_to', '').strip()
                
                # Check for valid comment/reply combinations
                if not comment:
                    if reply_to:
                        self.log(f"\nError: Account {email} has a reply_to but no comment")
                        self.stats["failed"] += 1
                        self.update_stats()
                        self.update_status(index, "Invalid Config")
                        continue
                    else:
                        self.log(f"\nSkipping account {email}: No comment specified")
                        self.stats["skipped"] += 1
                        self.update_stats()
                        self.update_status(index, "Skipped")
                        continue

                password = row['password'].strip()
                totp_secret = row['2fa_secret'].strip()
                proxy = row['proxy'].strip()
                post_url = row['post_url'].strip()
                image_path = row.get('image_path')

                profile_name = email.split('@')[0]
                self.log(f"\nProcessing account: {email}")
                self.update_status(index, "Processing")

                driver = self.setup_chrome_profile(profile_name, proxy if proxy else None)

                try:
                    if self.login_facebook(driver, email, password, totp_secret):
                        self.log("Login successful")
                        self.random_delay()
                            
                        if self.post_comment(driver, post_url, comment, reply_to, image_path):
                            self.log(f"Successfully processed account: {email}")
                            self.stats["success"] += 1
                            self.update_status(index, "Success")
                            comments_in_session += 1
                        else:
                            self.log(f"Failed to post comment for account: {email}")
                            self.stats["failed"] += 1
                            self.update_status(index, "Failed")
                    else:
                        self.log(f"Login failed for account: {email}")
                        self.stats["failed"] += 1
                        self.update_status(index, "Login Failed")
                finally:
                    driver.quit()

                progress = ((index + 1) / total_accounts) * 100
                self.update_progress(progress)
                self.update_stats()

            except Exception as e:
                self.log(f"Error processing account {email}: {str(e)}")
                self.stats["failed"] += 1
                self.update_stats()
                self.update_status(index, "Error")
                continue

            self.random_delay("comment")

class CommentSpinner:
    def __init__(self):
        self.random = random.Random()

    def set_seed(self, seed):
        """Set random seed for reproducible results"""
        self.random.seed(seed)

    def spin(self, text):
        """Process a text with spinning syntax and return a spun version"""
        if not text:
            return ""
            
        # Process nested spintax first
        while '{' in text and '}' in text:
            text = self._process_outermost_brackets(text)
            
        # Process optional text
        while '[' in text and ']' in text:
            text = self._process_optional_text(text)
            
        return text.strip()
        
    def _process_outermost_brackets(self, text):
        """Process the outermost level of spinning syntax"""
        start = text.find('{')
        if start == -1:
            return text
            
        # Find matching closing bracket
        bracket_count = 1
        pos = start + 1
        
        while pos < len(text) and bracket_count > 0:
            if text[pos] == '{':
                bracket_count += 1
            elif text[pos] == '}':
                bracket_count -= 1
            pos += 1
            
        if bracket_count > 0:
            return text  # Unmatched brackets, return as-is
            
        end = pos - 1
        
        # Extract options and choose one
        options = text[start + 1:end].split('|')
        if not options:
            return text
            
        chosen = self.random.choice(options).strip()
        
        # Replace the spintax with the chosen option
        return text[:start] + chosen + text[end + 1:]
        
    def _process_optional_text(self, text):
        """Process optional text in square brackets"""
        start = text.find('[')
        if start == -1:
            return text
            
        end = text.find(']', start)
        if end == -1:
            return text
            
        # 50% chance to include optional text
        if self.random.random() < 0.5:
            # Include the text without brackets
            return text[:start] + text[start + 1:end] + text[end + 1:]
        else:
            # Remove the optional text and brackets
            return text[:start] + text[end + 1:]
            
    def get_all_variations(self, text, max_variations=100):
        """Get all possible variations of the spun text (up to max_variations)"""
        variations = set()
        for _ in range(max_variations):
            variations.add(self.spin(text))
            if len(variations) >= max_variations:
                break
        return list(variations)