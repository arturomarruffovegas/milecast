import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = BASE_DIR / "frontend" / "dist"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or secrets.token_urlsafe(48)
DEBUG = False
# Identify the site to OpenStreetMap when the browser requests map tiles.
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "testserver"]
if hostname := os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(hostname)
if extra_hosts := os.environ.get("DJANGO_ALLOWED_HOSTS"):
    ALLOWED_HOSTS.extend(host.strip() for host in extra_hosts.split(",") if host.strip())

ROOT_URLCONF = "server.urls"
WSGI_APPLICATION = "server.wsgi.application"
INSTALLED_APPS = ["django.contrib.staticfiles"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
STATIC_URL = "/static/"
STATICFILES_DIRS = [DIST_DIR] if DIST_DIR.is_dir() else []
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
}
USE_TZ = True
TIME_ZONE = "UTC"
DATA_UPLOAD_MAX_MEMORY_SIZE = 8192
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "OPTIONS": {"MAX_ENTRIES": 2000},
    },
    "routing": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "truck-routes",
        "OPTIONS": {"MAX_ENTRIES": 16},
    },
}
