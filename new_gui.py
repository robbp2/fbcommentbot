import sys
import os
import random
import csv
import json
import pyotp
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, 
    QHBoxLayout, QPushButton, QLabel, QFileDialog, 
    QTextEdit, QScrollArea, QProgressBar, QCheckBox,
    QDialog, QTableWidgetItem
)
from PyQt6.QtGui import QColor
from ui_mainwindow import Ui_MainWindow
from facebook_commenter import FacebookCommenter
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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
    waiting_for_2fa = pyqtSignal(str, str)  # Modified to include totp_secret
    totp_code_update = pyqtSignal(str)  # New signal for TOTP updates
    totp_code_generated = pyqtSignal(str)  # New signal for TOTP codes

    def __init__(self, csv_path, image_paths, main_window, filters):
        super().__init__()
        self.csv_path = csv_path
        self.image_paths = image_paths
        self.main_window = main_window
        self.filters = filters
        self.is_running = True
        self.current_driver = None
        self.waiting_for_2fa_completion = False
        self.current_email = None
        self.current_totp_secret = None
        self.totp_timer = None
        self.bot = FacebookCommenter(
            csv_path,
            log_callback=lambda msg: self.log.emit(msg),
            progress_callback=lambda val: self.progress.emit(int(val)),
            status_callback=self.handle_status_callback,
            stats_callback=lambda stats: self.stats_update.emit(stats)
        )

    def run(self):
        try:
            data = self.bot.read_csv_data()
            modified_data = []
            success_count = 0
            failed_count = 0
            skipped_count = 0

            for i, row in enumerate(data):
                if not self.is_running:
                    break

                # Check if this profile should be processed based on filters
                if not self.should_process_profile(row, i):
                    skipped_count += 1
                    self.status_update.emit(str(i), "Filtered")
                    self.stats_update.emit({
                        "success": success_count,
                        "failed": failed_count,
                        "skipped": skipped_count
                    })
                    continue

                # Get current comment from UI
                current_comment = self.main_window.ui.previewTable.get_comment(i).strip()
                reply_to = row.get('reply_to', '').strip()

                # Skip if no comment or only reply_to without comment
                if not current_comment:
                    if reply_to:
                        self.log.emit(f"\nError: Account has a reply_to but no comment")
                        failed_count += 1
                        self.status_update.emit(str(i), "No Comment")
                    else:
                        self.log.emit(f"\nSkipping account: No comment specified")
                        skipped_count += 1
                        self.status_update.emit(str(i), "No Comment")
                    
                    self.stats_update.emit({
                        "success": success_count,
                        "failed": failed_count,
                        "skipped": skipped_count
                    })
                    continue

                # Update row data with current comment from UI
                row_copy = row.copy()
                row_copy['comment'] = current_comment
                
                if i in self.image_paths and self.image_paths[i]:
                    row_copy['image_path'] = self.image_paths[i]
                
                email = row_copy['email'].strip()
                password = row_copy['password'].strip()
                totp_secret = row_copy['2fa_secret'].strip()
                proxy = row_copy['proxy'].strip()
                post_url = row_copy['post_url'].strip()  # Get post_url here
                
                self.log.emit(f"\nProcessing account: {email}")
                self.status_update.emit(str(i), "Processing")
                profile_name = email.split('@')[0]

                # Always close any existing driver before starting a new profile
                # (unless we're in the middle of 2FA)
                if not self.waiting_for_2fa_completion and self.current_driver:
                    try:
                        self.log.emit("Closing previous browser session...")
                        self.current_driver.quit()
                        self.current_driver = None
                        time.sleep(2)  # Give time for cleanup
                    except Exception as e:
                        self.log.emit(f"Error closing previous browser: {str(e)}")

                try:
                    # Create new driver for this profile if not in 2FA
                    if not self.current_driver:
                        driver = self.bot.setup_chrome_profile(profile_name, proxy if proxy else None)
                        self.current_driver = driver
                    else:
                        driver = self.current_driver

                    if not self.waiting_for_2fa_completion:  # Only try to login if not waiting for 2FA
                        login_result, saved_driver, received_totp_secret = self.bot.login_facebook(driver, email, password, totp_secret)
                        if login_result == "2fa":
                            self.current_driver = saved_driver
                            self.waiting_for_2fa_completion = True
                            self.current_totp_secret = received_totp_secret
                            self.waiting_for_2fa.emit(email, received_totp_secret)
                            self.log.emit(f"Debug: login_facebook returned totp_secret: {received_totp_secret}")
                            self.start_totp_generation(received_totp_secret)
                            
                            # Wait for 2FA completion
                            while self.waiting_for_2fa_completion and self.is_running:
                                time.sleep(1)
                                
                            if not self.is_running:
                                break
                                
                            self.stop_totp_generation()
                            self.waiting_for_2fa_completion = False

                    # If we have a valid driver (either from successful login or after 2FA)
                    if self.current_driver:
                        # Try to post the comment
                        if self.bot.post_comment(self.current_driver, post_url, current_comment, reply_to, row_copy.get('image_path')):
                            self.log.emit(f"Successfully posted comment for account: {email}")
                            success_count += 1
                            self.status_update.emit(str(i), "Success")
                            modified_data.append(row_copy)
                        else:
                            self.log.emit(f"Failed to post comment for account: {email}")
                            failed_count += 1
                            self.status_update.emit(str(i), "Failed")
                        
                        # Close browser after successful posting (unless in 2FA)
                        if not self.waiting_for_2fa_completion:
                            self.log.emit("Closing browser after comment...")
                            self.current_driver.quit()
                            self.current_driver = None
                            time.sleep(2)  # Give time for cleanup
                    
                except Exception as e:
                    self.log.emit(f"Error processing account {email}: {str(e)}")
                    failed_count += 1
                    self.status_update.emit(str(i), "Error")
                    if not self.waiting_for_2fa_completion and self.current_driver:
                        try:
                            self.current_driver.quit()
                            self.current_driver = None
                        except:
                            pass
                    continue

                # Update progress
                progress = int(((i + 1) / len(data)) * 100)
                self.progress.emit(progress)
                
                # Update stats
                self.stats_update.emit({
                    "success": success_count,
                    "failed": failed_count,
                    "skipped": skipped_count
                })

            # Final cleanup
            try:
                if self.current_driver:
                    self.log.emit("Closing browser session...")
                    self.current_driver.quit()
                    self.current_driver = None
                    self.log.emit("Browser session closed successfully")
            except Exception as e:
                self.log.emit(f"Error closing browser: {str(e)}")
                
            # Final progress update
            self.progress.emit(100)
            
            # Final stats update - maintain the correct counts
            self.stats_update.emit({
                "success": success_count,
                "failed": failed_count,
                "skipped": skipped_count
            })
                
        except Exception as e:
            self.log.emit(f"Bot error: {str(e)}")

    def should_process_profile(self, row, index):
        """Check if profile should be processed based on filters"""
        if not any([self.filters['male_only'], self.filters['female_only'], self.filters['seniors_only']]):
            return True  # No filters active, process all profiles
            
        sex = row.get('sex', '').strip().lower()
        is_senior = str(row.get('senior', '')).strip().lower() == 'true'
        
        if self.filters['male_only'] and sex != 'male':
            self.log.emit(f"\nSkipping profile at row {index + 1}: Does not match Male Only filter")
            return False
            
        if self.filters['female_only'] and sex != 'female':
            self.log.emit(f"\nSkipping profile at row {index + 1}: Does not match Female Only filter")
            return False
            
        if self.filters['seniors_only'] and not is_senior:
            self.log.emit(f"\nSkipping profile at row {index + 1}: Does not match Seniors Only filter")
            return False
            
        return True

    def generate_totp(self):
        """Generate new TOTP code and emit it only if we have a valid secret"""
        if not self.current_totp_secret:
            self.log.emit("No TOTP secret available for code generation")
            return
            
        try:
            # Clean the secret of spaces and validate
            clean_secret = self.current_totp_secret.replace(" ", "")
            if not clean_secret:
                self.log.emit("Invalid TOTP secret (empty after cleaning)")
                return
                
            totp = pyotp.TOTP(clean_secret)
            code = totp.now()
            self.log.emit(f"Generated new TOTP code: {code}")
            self.totp_code_generated.emit(code)
        except Exception as e:
            self.log.emit(f"Error generating TOTP code: {str(e)}")

    def start_totp_generation(self, totp_secret):
        """Start TOTP code generation timer with proper cleanup"""
        if not totp_secret:
            self.log.emit("Cannot start TOTP generation: No secret provided")
            return
            
        # Stop existing timer if any
        self.stop_totp_generation()
        
        # Store new secret and start generation
        self.current_totp_secret = totp_secret
        self.log.emit(f"Debug: Starting TOTP generation with secret: {totp_secret}")
        
        # Generate first code immediately
        self.generate_totp()
        
        # Create and start new timer
        self.totp_timer = QTimer(self)
        self.totp_timer.timeout.connect(self.generate_totp)
        
        # Calculate time until next 30-second interval
        current_time = int(time.time())
        seconds_until_next = 30 - (current_time % 30)
        
        # Start timer to align with 30-second intervals
        self.totp_timer.start(30000)  # Fixed 30-second intervals

    def stop_totp_generation(self):
        """Stop TOTP code generation and clean up"""
        if self.totp_timer:
            self.totp_timer.stop()
            self.totp_timer.deleteLater()
            self.totp_timer = None
            self.log.emit("TOTP generation stopped")
        
        self.current_totp_secret = None

    def stop(self):
        """Stop the bot and cleanup"""
        self.is_running = False
        self.stop_totp_generation()

    def handle_status_callback(self, status, email):
        """Handle status updates from the bot"""
        if status == "2fa_required":
            self.waiting_for_2fa_completion = True
            self.current_email = email
            if self.current_totp_secret:  # Only emit if we have a valid secret
                self.waiting_for_2fa.emit(email, self.current_totp_secret)

    def continue_after_2fa(self):
        """Continue bot operation after 2FA is complete"""
        self.log.emit("Resuming operation after 2FA...")
        self.waiting_for_2fa_completion = False
        self.stop_totp_generation()
        
        # Resume Facebook operations if we have a saved driver
        if self.current_driver:
            try:
                # Wait for a short time to ensure 2FA is processed
                time.sleep(3)
                # Verify we're logged in
                WebDriverWait(self.current_driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "[aria-label='Facebook']"))
                )
                self.log.emit("Successfully verified login after 2FA")
            except Exception as e:
                self.log.emit(f"Error verifying login after 2FA: {str(e)}")
                if self.current_driver:
                    self.current_driver.quit()
                    self.current_driver = None



class MainWindow(QMainWindow):
    SEX_COL = 5  # Adjust number based on your table structure
    SENIOR_COL = 6  # Adjust number based on your table structure

    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.current_totp = None  # Store current TOTP code

        # Add this line after setupUi
        self.setup_profile_filters()

        
        
        # Connect signals
        self.ui.selectFileBtn.clicked.connect(self.select_file)
        self.ui.startBtn.clicked.connect(self.start_bot)
        self.ui.stopBtn.clicked.connect(self.stop_bot)
        self.ui.continueBtn.clicked.connect(self.copy_2fa_code)
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
                        row['name'],  # Add name column
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

        # Get current filter state
        filters = {
            'male_only': self.maleOnlyCheckbox.isChecked(),
            'female_only': self.femaleOnlyCheckbox.isChecked(),
            'seniors_only': self.seniorsOnlyCheckbox.isChecked()
        }

        self.ui.startBtn.setEnabled(False)
        self.ui.stopBtn.setEnabled(True)
        self.ui.progressBar.setValue(0)
        
        self.bot_thread = BotWorker(self.csv_path, image_paths, self, filters)
        self.bot_thread.progress.connect(self.update_progress)
        self.bot_thread.log.connect(self.log)
        self.bot_thread.waiting_for_2fa.connect(self.handle_2fa_wait)
        self.bot_thread.stats_update.connect(self.handle_stats_update)
        self.bot_thread.status_update.connect(self.update_row_status)
        self.bot_thread.finished.connect(self.bot_finished)
        self.bot_thread.totp_code_generated.connect(self.handle_totp_code_generated)
        self.bot_thread.start()

    def clear_images(self):
        self.ui.previewTable.clear_images()
        self.log("Cleared all images")

    def stop_bot(self):
        if self.bot_thread and self.bot_thread.isRunning():
            self.bot_thread.stop()
            self.log("Stopping bot...")
            self.ui.stopBtn.setEnabled(False)

    def copy_2fa_code(self):
        """Copy current TOTP code to clipboard and prepare for continuation"""
        if self.current_totp:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.current_totp)
            self.log("2FA code copied to clipboard")
            
            # Change button text and function
            self.ui.continueBtn.setText("Continue After 2FA")
            try:
                self.ui.continueBtn.clicked.disconnect()
            except:
                pass
            self.ui.continueBtn.clicked.connect(self.continue_after_2fa)
            self.log("Click 'Continue After 2FA' after entering the code")
        else:
            self.log("Error: No TOTP code available to copy.")
    
    def continue_after_2fa(self):
        """Signal the bot to continue after 2FA is complete"""
        self.log("Continuing after 2FA verification...")
        if self.bot_thread:
            self.bot_thread.continue_after_2fa()
            self.ui.continueBtn.setEnabled(False)
            # Reset button text and function
            self.ui.continueBtn.setText("Copy 2FA Code")
            try:
                self.ui.continueBtn.clicked.disconnect()
            except:
                pass
            self.ui.continueBtn.clicked.connect(self.copy_2fa_code)

    def update_progress(self, value):
        self.ui.progressBar.setValue(value)
        self.ui.progressLabel.setText(f"{value}%")
        self.ui.statusbar.showMessage(f"Progress: {value}%")

    def update_row_status(self, row_id, status):
        """Update the status column in the preview table"""
        try:
            row = int(row_id)
            item = QTableWidgetItem(status)
            
            # Set color based on status
            if status == "Success":
                item.setForeground(QColor("#28a745"))  # Green
            elif status == "Failed":
                item.setForeground(QColor("#dc3545"))  # Red
            elif status == "Filtered" or status == "No Comment":
                item.setForeground(QColor("#6c757d"))  # Gray
            elif status == "Processing":
                item.setForeground(QColor("#007bff"))  # Blue
                
            self.ui.previewTable.setItem(row, 4, item)  # Assuming status is column 4
        except Exception as e:
            self.log(f"Error updating status: {str(e)}")

    def handle_stats_update(self, stats_dict):
        """Update the stats display"""
        self.stats.success = stats_dict.get('success', 0)
        self.stats.failed = stats_dict.get('failed', 0)
        self.stats.skipped = stats_dict.get('skipped', 0)
        self.update_stats()

    def handle_2fa_wait(self, email, totp_secret):
        """Handle bot pause on 2FA page"""
        self.ui.continueBtn.setEnabled(True)
        self.ui.continueBtn.setText("Copy 2FA Code")  # Reset button text
        self.current_totp = None  # Clear any old TOTP code
        
        try:
            self.ui.continueBtn.clicked.disconnect()
        except:
            pass
        self.ui.continueBtn.clicked.connect(self.copy_2fa_code)
        
        self.log(f"Waiting for 2FA verification for {email}")
        self.log("Click 'Copy 2FA Code' to copy the code to clipboard")
        
        if not totp_secret:
            self.log("Error: No TOTP secret provided for generation.")
            return
            
        # Start TOTP generation in bot thread
        if self.bot_thread:
            # Disconnect any existing connections
            try:
                self.bot_thread.totp_code_generated.disconnect()
            except:
                pass
            # Connect the signal
            self.bot_thread.totp_code_generated.connect(self.handle_totp_code_generated)
            self.bot_thread.start_totp_generation(totp_secret)

    def handle_totp_code_generated(self, code):
        """Handle newly generated TOTP code"""
        self.current_totp = code
        self.log(f"TOTP code received: {code}")

    def handle_totp_update(self, code):
        self.current_totp = code

    
    def handle_device_approval(self, email):
        self.ui.continueBtn.setEnabled(True)
        self.log(f"Waiting for device approval for {email}")
        self.log("Approve the login from your other device")
        self.log("Then click 'Continue After 2FA' button")

    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.ui.logTextEdit.append(f"[{timestamp}] {message}")
        scrollbar = self.ui.logTextEdit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def bot_finished(self):
        """Handle bot completion"""
        self.ui.startBtn.setEnabled(True)
        self.ui.stopBtn.setEnabled(False)
        self.ui.continueBtn.setEnabled(False)
        if self.bot_thread:
            self.bot_thread.stop_totp_generation()  # Ensure TOTP generation is stopped
        self.log("Bot finished running")
        self.save_progress()

    def save_progress(self):
        if not self.csv_path:
            return
            
        try:
            save_path = f"{os.path.splitext(self.csv_path)[0]}_progress.csv"
            with open(save_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                headers = ['Name', 'Email', 'Comment', 'Reply To', 'Status', 'Sex', 'Senior']
                writer.writerow(headers)
                
                for row in range(self.ui.previewTable.rowCount()):
                    row_data = []
                    for col in range(self.ui.previewTable.columnCount() - 1):  # Exclude image column
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
    def launch_profile(self, row):
        """Launch browser profile for the selected row"""
        try:
            # Get email from the QLabel inside the widget in column 1 (email column)
            email_widget = self.ui.previewTable.cellWidget(row, 1)  # Changed from 0 to 1
            email = email_widget.layout().itemAt(0).widget().text()
            
            proxy = None
            
            # Try to get proxy from original CSV
            with open(self.csv_path, 'r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file)
                for i, csv_row in enumerate(reader):
                    if i == row:
                        proxy = csv_row.get('proxy', '').strip()
                        break
            
            profile_name = email.split('@')[0]
            self.log(f"Launching profile for: {email}")
            
            # Create commenter instance just for profile setup
            commenter = FacebookCommenter(
                self.csv_path,
                log_callback=self.log
            )
            
            # Store driver reference as instance variable
            if not hasattr(self, 'launched_drivers'):
                self.launched_drivers = {}
            
            # Close existing driver for this profile if it exists
            if profile_name in self.launched_drivers:
                try:
                    self.launched_drivers[profile_name].quit()
                except:
                    pass
            
            # Setup and launch browser
            self.launched_drivers[profile_name] = commenter.setup_chrome_profile(profile_name, proxy if proxy else None)
            self.launched_drivers[profile_name].get('https://www.facebook.com')
            
            self.log(f"Browser launched for {email}")
            
        except Exception as e:
            self.log(f"Error launching profile: {str(e)}")

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
            
            # Use existing ChromeDriver path function
            fb_commenter = FacebookCommenter(self.csv_path)
            chromedriver_path = fb_commenter.get_chromedriver_path()
            service = Service(executable_path=chromedriver_path)
            
            # Create extension for authentication
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
            
            driver = webdriver.Chrome(service=service, options=options)
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