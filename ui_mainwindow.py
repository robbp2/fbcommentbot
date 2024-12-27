from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWidgets import (QTableWidget, QTableWidgetItem, QLabel, 
                           QWidget, QHBoxLayout, QPushButton)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDragEnterEvent, QDropEvent, QPalette, QColor

class ImageDropArea(QLabel):
    imageDropped = pyqtSignal(str)  # Signal emitted when image is dropped

    def __init__(self):
        super().__init__()
        self.setMinimumSize(60, 60)
        self.setFixedHeight(60)      # Force height to be consistent
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setText("Drop\nImage")
        self.setStyleSheet("""
            QLabel {
                border: 2px dashed #aaa;
                border-radius: 5px;
                background-color: #f5f5f5;
                padding: 5px;
                font-size: 10px;
                color: #666;
            }
        """)
        self.setAcceptDrops(True)
        self.image_path = None

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            image_path = urls[0].toLocalFile()
            if image_path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
                self.image_path = image_path
                self.setPixmap(QtGui.QPixmap(image_path).scaled(
                    50, 50, Qt.AspectRatioMode.KeepAspectRatio))
                self.imageDropped.emit(image_path)
            else:
                self.setText("Invalid\nImage")

    def clear_image(self):
        self.image_path = None
        self.setText("Drop\nImage")
        self.setPixmap(QtGui.QPixmap())

class AccountTableWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_areas = {}  # Store image drop areas by row
        self.setColumnCount(7)  # Email, Comment, Reply To, Status, Image, gender, senior
        self.setHorizontalHeaderLabels(["Email", "Comment", "Reply To", "Status", "Sex", "Senior" "Image"])
        self.verticalHeader().setDefaultSectionSize(70)  # Set row height to accommodate image box
        
    def add_row(self, row_data):
        row = self.rowCount()
        self.insertRow(row)
        
        # Add text items
        for col, text in enumerate(row_data[:6]):  # Changed from 4 to 6 columns for text
            self.setItem(row, col, QTableWidgetItem(str(text)))
        
        # Add image drop area
        image_area = ImageDropArea()
        self.image_areas[row] = image_area
        self.setCellWidget(row, 6, image_area)  # Changed from 4 to 6 for image column
        
        # Make all columns stretch except the image column 
        self.horizontalHeader().setSectionResizeMode(
            6, QtWidgets.QHeaderView.ResizeMode.Fixed)  # Changed from 4 to 6
        self.setColumnWidth(6, 70)  # Changed from 4 to 6

    def get_image_path(self, row):
        if row in self.image_areas:
            return self.image_areas[row].image_path
        return None

    def clear_images(self):
        for image_area in self.image_areas.values():
            image_area.clear_image()

class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.resize(1000, 800)
        self.centralwidget = QtWidgets.QWidget(parent=MainWindow)
        
        # Main vertical layout
        self.verticalLayout = QtWidgets.QVBoxLayout(self.centralwidget)
        
        # File selection layout
        self.fileLayout = QtWidgets.QHBoxLayout()
        self.fileLabel = QtWidgets.QLabel("No file selected")
        self.selectFileBtn = QtWidgets.QPushButton("Select CSV File")
        self.fileLayout.addWidget(self.fileLabel)
        self.fileLayout.addWidget(self.selectFileBtn)
        self.verticalLayout.addLayout(self.fileLayout)
        
        # Stats layout
        self.statsLayout = QtWidgets.QHBoxLayout()
        self.totalLabel = QtWidgets.QLabel("Total: 0")
        self.successLabel = QtWidgets.QLabel("Success: 0")
        self.failedLabel = QtWidgets.QLabel("Failed: 0")
        self.skippedLabel = QtWidgets.QLabel("Skipped: 0")
        self.statsLayout.addWidget(self.totalLabel)
        self.statsLayout.addWidget(self.successLabel)
        self.statsLayout.addWidget(self.failedLabel)
        self.statsLayout.addWidget(self.skippedLabel)
        self.verticalLayout.addLayout(self.statsLayout)
        
        # Custom table with image drop areas
        self.previewTable = AccountTableWidget()
        self.verticalLayout.addWidget(self.previewTable)
        
        # Control buttons layout
        self.controlLayout = QtWidgets.QHBoxLayout()
        self.startBtn = QtWidgets.QPushButton("Start Bot")
        self.stopBtn = QtWidgets.QPushButton("Stop Bot")
        self.continueBtn = QtWidgets.QPushButton("Continue After 2FA")
        self.testProxyBtn = QtWidgets.QPushButton("Test Proxies")
        self.clearImagesBtn = QtWidgets.QPushButton("Clear Images")
        self.controlLayout.addWidget(self.startBtn)
        self.controlLayout.addWidget(self.stopBtn)
        self.controlLayout.addWidget(self.continueBtn)
        self.controlLayout.addWidget(self.testProxyBtn)
        self.controlLayout.addWidget(self.clearImagesBtn)
        self.verticalLayout.addLayout(self.controlLayout)
        
        # Progress bar with percentage label
        self.progressLayout = QtWidgets.QHBoxLayout()
        self.progressBar = QtWidgets.QProgressBar()
        self.progressLabel = QtWidgets.QLabel("0%")
        self.progressLayout.addWidget(self.progressBar)
        self.progressLayout.addWidget(self.progressLabel)
        self.verticalLayout.addLayout(self.progressLayout)
        
        # Log text area
        self.logTextEdit = QtWidgets.QTextEdit()
        self.logTextEdit.setReadOnly(True)
        self.verticalLayout.addWidget(self.logTextEdit)
        
        MainWindow.setCentralWidget(self.centralwidget)
        
        # Menu bar
        self.menubar = QtWidgets.QMenuBar(parent=MainWindow)
        self.menuFile = QtWidgets.QMenu("File", self.menubar)
        self.menuSettings = QtWidgets.QMenu("Settings", self.menubar)
        self.menuTools = QtWidgets.QMenu("Tools", self.menubar)
        
        self.actionLoad = QtGui.QAction("Load CSV", MainWindow)
        self.actionSave = QtGui.QAction("Save Progress", MainWindow)
        self.actionExit = QtGui.QAction("Exit", MainWindow)
        self.menuFile.addAction(self.actionLoad)
        self.menuFile.addAction(self.actionSave)
        self.menuFile.addAction(self.actionExit)
        
        self.actionSettings = QtGui.QAction("Bot Settings", MainWindow)
        self.menuSettings.addAction(self.actionSettings)
        
        self.actionTestProxies = QtGui.QAction("Test Proxies", MainWindow)
        self.actionVerifyAccounts = QtGui.QAction("Verify Accounts", MainWindow)
        self.menuTools.addAction(self.actionTestProxies)
        self.menuTools.addAction(self.actionVerifyAccounts)
        
        self.menubar.addMenu(self.menuFile)
        self.menubar.addMenu(self.menuSettings)
        self.menubar.addMenu(self.menuTools)
        MainWindow.setMenuBar(self.menubar)
        
        # Status bar
        self.statusbar = QtWidgets.QStatusBar(parent=MainWindow)
        MainWindow.setStatusBar(self.statusbar)
        
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

class AccountTableWidget(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_areas = {}  # Store image drop areas by row
        self.setColumnCount(7)  # Email, Comment, Reply To, Status, Image
        self.setHorizontalHeaderLabels(["Email", "Comment", "Reply To", "Status", "Sex", "Senior", "Image"])
        self.verticalHeader().setDefaultSectionSize(70)  # Set row height to accommodate image box

    def add_row(self, row_data):
        row = self.rowCount()
        self.insertRow(row)
        
        # Add text items
        for col, text in enumerate(row_data[:6]):  # First 4 columns are text
            item = QTableWidgetItem(str(text))
            if col == 1:  # Comment column
                # Add a small button to the cell
                widget = QWidget()
                layout = QHBoxLayout(widget)
                layout.setContentsMargins(0, 0, 0, 0)
                
                # Text item
                text_item = QTableWidgetItem(str(text))
                self.setItem(row, col, text_item)
                
                # Preview button
                preview_btn = QPushButton("✏️")  # Pencil emoji
                preview_btn.setFixedSize(24, 24)
                preview_btn.setToolTip("Edit comment with spinning syntax")
                preview_btn.clicked.connect(lambda checked, r=row: self.parent().parent().preview_comment(r))
                
                layout.addStretch()
                layout.addWidget(preview_btn)
                
                self.setCellWidget(row, col, widget)
            else:
                self.setItem(row, col, QTableWidgetItem(str(text)))
        
        # Add image drop area
        image_area = ImageDropArea()
        self.image_areas[row] = image_area
        self.setCellWidget(row, 6, image_area)
        
        # Make all columns stretch except the image column
        self.horizontalHeader().setSectionResizeMode(
            6, QtWidgets.QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(6, 70)

    def get_comment(self, row):
        return self.item(row, 1).text() if self.item(row, 1) else ""

    def set_comment(self, row, comment):
        if self.item(row, 1):
            self.item(row, 1).setText(comment)

    def get_image_path(self, row):
        if row in self.image_areas:
            return self.image_areas[row].image_path
        return None

    def clear_images(self):
        for image_area in self.image_areas.values():
            if image_area.pixmap() and not image_area.pixmap().isNull():
                image_area.clear()
                image_area.setText("Drop Image")
            elif not image_area.text():
                image_area.setText("Drop Image")