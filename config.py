# config.py – simple config for Render demo (no real DB)

import os

# Secret key for sessions
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

# Dummy MySQL values – not actually used on Render in demo mode
MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DB = os.environ.get("MYSQL_DB", "organ_donor_matcher")
