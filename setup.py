from setuptools import setup
import os
import sys
from PyQt6 import QtCore

# Get PyQt6 path
pyqt_path = os.path.dirname(QtCore.__file__)

# Create data_files list with PyQt6 files
pyqt_files = []
for root, dirs, files in os.walk(pyqt_path):
    for file in files:
        if file.endswith('.so') or file.endswith('.dylib'):
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, pyqt_path)
            dest_dir = os.path.join('PyQt6', os.path.dirname(rel_path))
            pyqt_files.append((dest_dir, [full_path]))

APP = ['new_gui.py']
DATA_FILES = [
    'facebook_commenter.py',
    'ui_mainwindow.py',
] + pyqt_files

OPTIONS = {
    'argv_emulation': True,
    'site_packages': True,
    'packages': [
        'PyQt6',
        'selenium',
        'pyotp',
        'certifi',
        'zipfile',
        'queue',
        'csv',
    ],
    'includes': [
        'facebook_commenter',
        'ui_mainwindow',
        'selenium.webdriver.chrome.service',
        'selenium.webdriver.common.by',
        'selenium.webdriver.support.ui',
        'selenium.webdriver.support.expected_conditions',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',
        'datetime',
        'queue',
        'os',
        'sys',
        'time',
        'random'
    ],
    'excludes': ['tkinter'],
    'iconfile': 'icon.icns',
    'plist': {
        'CFBundleName': "Facebook Comment Bot",
        'CFBundleDisplayName': "Facebook Comment Bot",
        'CFBundleGetInfoString': "Facebook Comment Automation Tool",
        'CFBundleIdentifier': "com.yourdomain.fbcommentbot",
        'CFBundleVersion': "1.0.0",
        'CFBundleShortVersionString': "1.0.0",
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.12',
    }
}

setup(
    name="FacebookCommentBot",
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)