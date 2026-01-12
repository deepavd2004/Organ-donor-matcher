import os

# Secret key for sessions
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key")

MYSQL_HOST = os.environ.get("MYSQL_HOST", "shinkansen.proxy.rlwy.net")
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "zonuwLbXLwFWiQTChisgQhPVDLWWEzON")
MYSQL_DB = os.environ.get("MYSQL_DB", "railway")
