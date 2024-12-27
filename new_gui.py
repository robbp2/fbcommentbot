import sys
import os
import random
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, 
    QHBoxLayout, QPushButton, QLabel, QFileDialog, 
    QTextEdit, QScrollArea, QProgressBar, QCheckBox,
    QDialog, QTableWidgetItem
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from ui_mainwindow import Ui_MainWindow
from facebook_commenter import FacebookCommenter
from datetime import datetime
import csv
import json
from selenium import webdriver
from comment_preview import CommentPreviewDialog
from facebook_commenter import FacebookCommenter, CommentSpinner  # Add CommentSpinner to import

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

class Stats:
    def __init__(self):
        self.total = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0

class BotWorker(QThread):
    progress = pyqtSignal(int)
    log = pyqtSignal(str)
    stats_update = pyqtSignal(dict)
    status_update = pyqtSignal(str, str)
    waiting_for_2fa = pyqtSignal(str)

    def __init__(self, csv_path, image_paths):
        super().__init__()
        self.csv_path = csv_path
        self.image_paths = image_paths  # Dictionary of row -> image path
        self.bot = FacebookCommenter(
            csv_path,
            log_callback=lambda msg: self.log.emit(msg),
            progress_callback=lambda val: self.progress.emit(int(val)),
            status_callback=lambda row, status: self.status_update.emit(str(row), status),
            stats_callback=lambda stats: self.stats_update.emit(stats)
        )
        self.is_running = True

    def run(self):
        try:
            data = self.bot.read_csv_data()
            # Convert data to list of dicts with image paths
            modified_data = []
            for i, row in enumerate(data):
                row_copy = row.copy()
                if i in self.image_paths and self.image_paths[i]:
                    row_copy['image_path'] = self.image_paths[i]
                modified_data.append(row_copy)
            # Run bot with modified data
            self.bot.data = modified_data
            self.bot.run()
        except Exception as e:
            self.log.emit(f"Bot error: {str(e)}")

    def stop(self):
        self.is_running = False
        self.bot.stop()

class MainWindow(QMainWindow):
    SEX_COL = 4  # Adjust number based on your table structure
    SENIOR_COL = 5  # Adjust number based on your table structure

    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        

        # Add this line after setupUi
        self.setup_profile_filters()

        
        
        # Connect signals
        self.ui.selectFileBtn.clicked.connect(self.select_file)
        self.ui.startBtn.clicked.connect(self.start_bot)
        self.ui.stopBtn.clicked.connect(self.stop_bot)
        self.ui.continueBtn.clicked.connect(self.continue_after_2fa)
        self.ui.testProxyBtn.clicked.connect(self.test_proxies)
        self.ui.clearImagesBtn.clicked.connect(self.clear_images)
        
        self.ui.actionLoad.triggered.connect(self.select_file)
        self.ui.actionSave.triggered.connect(self.save_progress)
        self.ui.actionExit.triggered.connect(self.close)
        
        # Initial button states
        self.ui.startBtn.setEnabled(False)
        self.ui.stopBtn.setEnabled(False)
        self.ui.continueBtn.setEnabled(False)
        self.ui.testProxyBtn.setEnabled(False)
        
        self.csv_path = None
        self.bot_thread = None
        self.stats = Stats()
        
        # Initial log message
        self.log("Welcome to Facebook Comment Bot")
        self.log("Please select a CSV file to begin")
        
        # Set up the preview table
        self.ui.previewTable.horizontalHeader().setStretchLastSection(True)
        self.ui.previewTable.setColumnWidth(0, 200)  # Email
        self.ui.previewTable.setColumnWidth(1, 300)  # Comment
        self.ui.previewTable.setColumnWidth(2, 200)  # Reply To

    def select_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Select CSV File",
            "",
            "CSV Files (*.csv);;All Files (*)"
        )
        if file_name:
            self.csv_path = file_name
            self.ui.fileLabel.setText(os.path.basename(file_name))
            self.ui.startBtn.setEnabled(True)
            self.ui.testProxyBtn.setEnabled(True)
            self.log(f"Selected file: {file_name}")
            self.load_preview()

    def load_preview(self):
        try:
            with open(self.csv_path, 'r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file)
                rows = list(reader)
                
                # Clear existing items
                self.ui.previewTable.setRowCount(0)
                
                # Add rows with image drop areas
                for row in rows:
                    row_data = [
                        row['email'],
                        row.get('comment', ''),
                        row.get('reply_to', ''),
                        'Pending',
                        row.get('sex', ''),
                        row.get('senior', '')
                    ]
                    self.ui.previewTable.add_row(row_data)
                
                self.stats.total = len(rows)
                self.update_stats()
                
        except Exception as e:
            self.log(f"Error loading preview: {str(e)}")

    def update_stats(self):
        self.ui.totalLabel.setText(f"Total: {self.stats.total}")
        self.ui.successLabel.setText(f"Success: {self.stats.success}")
        self.ui.failedLabel.setText(f"Failed: {self.stats.failed}")
        self.ui.skippedLabel.setText(f"Skipped: {self.stats.skipped}")

    def start_bot(self):
        if not self.csv_path:
            self.log("Please select a CSV file first")
            return

        # Collect image paths from drop areas
        image_paths = {}
        for row, image_area in self.ui.previewTable.image_areas.items():
            if image_area.image_path:
                image_paths[row] = image_area.image_path

        self.ui.startBtn.setEnabled(False)
        self.ui.stopBtn.setEnabled(True)
        self.ui.progressBar.setValue(0)
        
        self.bot_thread = BotWorker(self.csv_path, image_paths)
        self.bot_thread.progress.connect(self.update_progress)
        self.bot_thread.log.connect(self.log)
        self.bot_thread.waiting_for_2fa.connect(self.handle_2fa_wait)
        self.bot_thread.stats_update.connect(self.handle_stats_update)
        self.bot_thread.status_update.connect(self.update_row_status)
        self.bot_thread.finished.connect(self.bot_finished)
        self.bot_thread.start()

    def clear_images(self):
        self.ui.previewTable.clear_images()
        self.log("Cleared all images")

    def stop_bot(self):
        if self.bot_thread and self.bot_thread.isRunning():
            self.bot_thread.stop()
            self.log("Stopping bot...")
            self.ui.stopBtn.setEnabled(False)

    def continue_after_2fa(self):
        if self.bot_thread and self.bot_thread.wait_for_2fa:
            self.bot_thread.continue_2fa()
            self.ui.continueBtn.setEnabled(False)
            self.log("Continuing after 2FA verification...")

    def update_progress(self, value):
        self.ui.progressBar.setValue(value)
        self.ui.progressLabel.setText(f"{value}%")
        self.ui.statusbar.showMessage(f"Progress: {value}%")

    def update_row_status(self, row_id, status):
        self.ui.previewTable.setItem(int(row_id), 3, QTableWidgetItem(status))

    def handle_stats_update(self, stats_dict):
        self.stats.success = stats_dict.get('success', 0)
        self.stats.failed = stats_dict.get('failed', 0)
        self.stats.skipped = stats_dict.get('skipped', 0)
        self.update_stats()

    def handle_2fa_wait(self, email):
        self.ui.continueBtn.setEnabled(True)
        self.log(f"Waiting for 2FA verification for {email}")
        self.log("Complete the 2FA verification in the browser")
        self.log("Then click 'Continue After 2FA' button")

    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ui.logTextEdit.append(f"[{timestamp}] {message}")
        scrollbar = self.ui.logTextEdit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def bot_finished(self):
        self.ui.startBtn.setEnabled(True)
        self.ui.stopBtn.setEnabled(False)
        self.ui.continueBtn.setEnabled(False)
        self.log("Bot finished running")
        self.save_progress()

    def save_progress(self):
        if not self.csv_path:
            return
            
        try:
            save_path = f"{os.path.splitext(self.csv_path)[0]}_progress.csv"
            with open(save_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                headers = ['Email', 'Comment', 'Reply To', 'Status']
                writer.writerow(headers)
                
                for row in range(self.ui.previewTable.rowCount()):
                    row_data = []
                    for col in range(self.ui.previewTable.columnCount()):
                        item = self.ui.previewTable.item(row, col)
                        row_data.append(item.text() if item else '')
                    writer.writerow(row_data)
                    
            self.log(f"Progress saved to {save_path}")
        except Exception as e:
            self.log(f"Error saving progress: {str(e)}")

    def test_proxies(self):
        if not self.csv_path:
            return
            
        QMessageBox.information(
            self,
            "Proxy Test",
            "Testing proxies...\nThis may take a few minutes.",
            QMessageBox.StandardButton.Ok
        )

    def verify_accounts(self):
        if not self.csv_path:
            return
            
        QMessageBox.information(
            self,
            "Account Verification",
            "Verifying accounts...\nThis may take a few minutes.",
            QMessageBox.StandardButton.Ok
        )

    def show_settings(self):
        QMessageBox.information(
            self,
            "Settings",
            "Settings dialog coming soon...",
            QMessageBox.StandardButton.Ok
        )
    def test_proxies(self):
        if not self.csv_path:
            QMessageBox.warning(
                self,
                "Error",
                "Please select a CSV file first",
                QMessageBox.StandardButton.Ok
            )
            return
        
        self.ui.testProxyBtn.setEnabled(False)
        self.ui.startBtn.setEnabled(False)
        self.ui.progressBar.setValue(0)
        
        self.proxy_tester = ProxyTester(self.csv_path)
        self.proxy_tester.log.connect(self.log)
        self.proxy_tester.progress.connect(self.update_progress)
        self.proxy_tester.finished.connect(self.proxy_test_finished)
        self.proxy_tester.start()

    def proxy_test_finished(self):
        self.ui.testProxyBtn.setEnabled(True)
        self.ui.startBtn.setEnabled(True)
        self.log("Proxy testing completed")
    
    def preview_comment(self, row):
        """Open comment preview dialog for the specified row"""
        current_comment = self.ui.previewTable.get_comment(row)
        spinner = CommentSpinner()
        
        dialog = CommentPreviewDialog(
            parent=self,
            comment_text=current_comment,
            spinner=spinner,
            total_profiles=self.ui.previewTable.rowCount(),
            current_row=row
        )
        total_rows = self.ui.previewTable.rowCount()
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_comment = dialog.get_comment()
            
            # If apply across is checked, handle all profiles including current
            if dialog.should_apply_across():
                # Get all possible variations
                all_variations = list(set(spinner.get_all_variations(new_comment)))
                random.shuffle(all_variations)
                
                # Calculate profiles we can update (including current row)
                variations_to_use = min(len(all_variations), total_rows - row)
                
                if variations_to_use > 0:
                    self.log(f"\nApplying {variations_to_use} unique variations to profiles:")
                    for i in range(variations_to_use):
                        variation = all_variations[i]
                        self.ui.previewTable.set_comment(row + i, variation)
                        self.log(f"Row {row + i + 1}: {variation}")
            else:
                self.ui.previewTable.set_comment(row, new_comment)
                self.log(f"Updated comment for row {row + 1}")
    
    def setup_profile_filters(self):
        # Create filter layout
        filter_widget = QWidget()
        self.filterLayout = QHBoxLayout(filter_widget)
        
        # Create checkboxes
        self.maleOnlyCheckbox = QCheckBox("Male Only")
        self.femaleOnlyCheckbox = QCheckBox("Female Only")
        self.seniorsOnlyCheckbox = QCheckBox("Seniors Only")
        
        # Add to layout
        self.filterLayout.addWidget(self.maleOnlyCheckbox)
        self.filterLayout.addWidget(self.femaleOnlyCheckbox)
        self.filterLayout.addWidget(self.seniorsOnlyCheckbox)
        
        # Add filter widget to main UI - adjust location as needed
        self.ui.verticalLayout.insertWidget(1, filter_widget)
        
        # Connect signals
        self.maleOnlyCheckbox.stateChanged.connect(self.handle_gender_filter)
        self.femaleOnlyCheckbox.stateChanged.connect(self.handle_gender_filter)
        self.seniorsOnlyCheckbox.stateChanged.connect(self.apply_filters)

    def handle_gender_filter(self, state):
        # Ensure only one gender filter can be active
        if self.sender() == self.maleOnlyCheckbox and state:
            self.femaleOnlyCheckbox.setChecked(False)
        elif self.sender() == self.femaleOnlyCheckbox and state:
            self.maleOnlyCheckbox.setChecked(False)
        self.apply_filters()

    def apply_filters(self):
        for row in range(self.ui.previewTable.rowCount()):
            show_row = True
            profile_data = self.get_profile_data(row)
            
            if self.maleOnlyCheckbox.isChecked():
                show_row = show_row and profile_data['sex'] == 'male'
            elif self.femaleOnlyCheckbox.isChecked():
                show_row = show_row and profile_data['sex'] == 'female'
                
            if self.seniorsOnlyCheckbox.isChecked():
                show_row = show_row and profile_data['senior'] == 'true'
                
            self.ui.previewTable.setRowHidden(row, not show_row)

    def get_profile_data(self, row):
        sex_item = self.ui.previewTable.item(row, self.SEX_COL)
        senior_item = self.ui.previewTable.item(row, self.SENIOR_COL)
        
        return {
            'sex': sex_item.text().strip().lower() if sex_item else '',
            'senior': senior_item.text().strip().lower() if senior_item else 'false'
        }

class ProxyTester(QThread):
    log = pyqtSignal(str)
    progress = pyqtSignal(int)
    
    def __init__(self, csv_path):
        super().__init__()
        self.csv_path = csv_path
        self.is_running = True

    def test_proxy(self, proxy):
        try:
            parts = proxy.split(':')
            if len(parts) != 4:
                return False, "Invalid proxy format"
                
            ip, port, username, password = parts
            
            options = webdriver.ChromeOptions()
            options.add_argument('--headless')
            options.add_argument('--disable-gpu')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument(f'--proxy-server=http://{ip}:{port}')
            
            # Create a proxy extension for authentication
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
                }
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
            """ % (ip, port, username, password)
            
            import tempfile
            import zipfile
            import os
            
            # Create extension
            temp_dir = tempfile.mkdtemp()
            extension_path = os.path.join(temp_dir, "proxy_auth.zip")
            
            with zipfile.ZipFile(extension_path, 'w') as zp:
                zp.writestr("manifest.json", manifest_json)
                zp.writestr("background.js", background_js)
            
            options.add_extension(extension_path)
            
            driver = webdriver.Chrome(options=options)
            try:
                driver.set_page_load_timeout(30)
                # Try accessing a reliable test site
                driver.get('https://www.google.com')
                
                # If we got here without an error, the proxy is working
                return True, "Proxy working correctly (Successfully accessed Google)"
                
            except Exception as e:
                return False, f"Connection test failed: {str(e)}"
            finally:
                driver.quit()
                # Clean up the temporary extension
                try:
                    os.remove(extension_path)
                    os.rmdir(temp_dir)
                except:
                    pass
                    
        except Exception as e:
            return False, f"Proxy test failed: {str(e)}"

    def run(self):
        try:
            with open(self.csv_path, 'r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file)
                rows = list(reader)
                total = len(rows)
                
                self.log.emit("\n=== Starting Proxy Tests ===")
                for i, row in enumerate(rows):
                    if not self.is_running:
                        break
                        
                    proxy = row.get('proxy', '').strip()
                    email = row.get('email', '').strip()
                    
                    if not proxy:
                        self.log.emit(f"No proxy found for {email}")
                        continue
                        
                    self.log.emit(f"\nTesting proxy for {email}:")
                    self.log.emit(f"Proxy: {proxy}")
                    
                    success, message = self.test_proxy(proxy)
                    status = "✅ Passed" if success else "❌ Failed"
                    self.log.emit(f"Status: {status}")
                    self.log.emit(f"Details: {message}")
                    
                    progress = ((i + 1) / total) * 100
                    self.progress.emit(int(progress))
                    
                self.log.emit("\n=== Proxy Testing Complete ===")
                
        except Exception as e:
            self.log.emit(f"Error reading CSV: {str(e)}")

    def stop(self):
        self.is_running = False

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())