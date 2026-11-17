"""
Copy this file to  config/local_settings.py  and fill in your own values.

local_settings.py is the Python version of Java's application.properties.
It is listed in .gitignore, so your passwords never go to GitHub.
"""

# --- Database (XAMPP default is user "root" with an empty password) ---------
DB_NAME = "customs_ticketing_py"
DB_USER = "root"
DB_PASSWORD = ""
DB_HOST = "localhost"
DB_PORT = "3306"

# --- Security ---------------------------------------------------------------
# Use a long random value. Never reuse the development one in production.
JWT_SECRET = "change-this-to-a-long-random-secret-at-least-32-characters"
JWT_EXPIRATION_HOURS = 7 * 24  # production checklist: 8

# --- Frontend ---------------------------------------------------------------
# Used for the links inside reset-password and welcome emails.
FRONTEND_URL = "http://localhost:5173"
# Browsers allowed to call this API. Add the real frontend address in production.
CORS_ALLOWED_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]

# --- Email ------------------------------------------------------------------
# Leave EMAIL_HOST_USER empty to print emails in the terminal instead of sending.
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587
EMAIL_HOST_USER = ""          # e.g. your-email@gmail.com
EMAIL_HOST_PASSWORD = ""      # Gmail App Password
EMAIL_USE_TLS = True

# --- Production only --------------------------------------------------------
# DEBUG = False
# ALLOWED_HOSTS = ["your-server-name-or-ip"]
