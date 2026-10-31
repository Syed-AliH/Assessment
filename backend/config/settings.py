import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.environ.get("DJANGO_DEBUG", "").lower() == "true"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or ("dev-only-key" if DEBUG else None)
if not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY must be set unless DJANGO_DEBUG=true")
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
# Render sets this to the service's public hostname.
if os.environ.get("RENDER_EXTERNAL_HOSTNAME"):
    ALLOWED_HOSTS.append(os.environ["RENDER_EXTERNAL_HOSTNAME"])

INSTALLED_APPS = ["rest_framework", "trips"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.common.CommonMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
USE_TZ = True
TIME_ZONE = "UTC"

# Nothing is persisted long term, so the app needs no database.
DATABASES = {}

FRONTEND_DIST = Path(os.environ.get("FRONTEND_DIST", BASE_DIR.parent / "frontend" / "dist"))
WHITENOISE_ROOT = FRONTEND_DIST if FRONTEND_DIST.exists() else None
WHITENOISE_MAX_AGE = 3600

REDIS_URL = os.environ.get("REDIS_URL", "")
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": REDIS_URL}
        if REDIS_URL
        else {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": os.environ.get("CACHE_DIR", BASE_DIR / ".cache"),
            "OPTIONS": {"MAX_ENTRIES": 50_000},
        }
    )
}

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
    "EXCEPTION_HANDLER": "trips.errors.api_exception_handler",
    # Each analysis spends API quota, so anonymous use has to be bounded.
    "DEFAULT_THROTTLE_RATES": {"analyze": "30/min", "geocode": "120/min"},
}

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True

TOMTOM_API_KEY = os.environ.get("TOMTOM_API_KEY", "")
OPEN_METEO_API_KEY = os.environ.get("OPEN_METEO_API_KEY", "")
# Dotted paths that replace a provider. Unset in production.
ROUTING_PROVIDER = os.environ.get("ROUTING_PROVIDER", "")
GEOCODER = os.environ.get("GEOCODER", "")

# Tractor-trailer empty weight, added to the load for truck road restrictions.
TRUCK_TARE_LB = float(os.environ.get("TRUCK_TARE_LB", 33_000))
WEATHER_CACHE_SECONDS = 60 * 60
ANALYSIS_CACHE_SECONDS = 60 * 60
