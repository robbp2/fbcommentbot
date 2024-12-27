# fbcommentbot

Simple python-based app to facilitate commenting on Facebook ad posts.

# Requirements
- Chrome
- ChromeDriver (install with 'brew install chromedriver' command in Terminal)
- Python
- PyQt6
- selenium
- pyotp
- py2app

# Features
- load profiles into individual Chrome browser profiles with proxies
- Test proxy connections
- Facebook login + 2FA verification
- Comment on any public Facebook post
- Include images with comments
- Reply to existing comments
- Filter profiles by gender and age
- Use spintax for comments

# Compiling the app
## macOS
1) In terminal, type `pip install PyQt6 selenium pyotp py2app`
2) In terminal, type `brew install chromedriver` to install ChromeDriver
3) In terminal, navigate to the directory where you downloaded the files
4) In terminal, type `python setup.py py2app` or `python3 setup.py py2app` if you have Python3
