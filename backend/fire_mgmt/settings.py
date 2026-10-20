import os
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG      = os.environ.get("DEBUG", "false").lower() == "true"
SECRET_KEY = os.environ.get("SECRET_KEY") or ("django-insecure-dev-only" if DEBUG else None)
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY must be set when DEBUG is false.")
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
CSRF_TRUSTED_ORIGINS = [o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE    = True
    SECURE_SSL_REDIRECT   = os.environ.get("SECURE_SSL_REDIRECT", "true").lower() == "true"
    # Start low; raise to 31536000 once HTTPS is confirmed stable
    SECURE_HSTS_SECONDS   = int(os.environ.get("SECURE_HSTS_SECONDS", "3600"))

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.gis',
    'storages',
    'core',
    'parcelas',
    'operatives',
    'fire_actions',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'fire_mgmt.urls'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'],
    'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.debug',
        'django.template.context_processors.request',
        'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages',
        'core.context_processors.map_keys',
    ]},
}]

WSGI_APPLICATION = 'fire_mgmt.wsgi.application'

LOGIN_URL          = '/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/login/'

DATABASES = {"default": {
    "ENGINE":   "django.contrib.gis.db.backends.postgis",
    "NAME":     os.environ.get("DB_NAME",     "firedb"),
    "USER":     os.environ.get("DB_USER",     "fireuser"),
    "PASSWORD": os.environ.get("DB_PASSWORD", "firepass"),
    "HOST":     os.environ.get("DB_HOST",     "localhost"),
    "PORT":     os.environ.get("DB_PORT",     "5432"),
}}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'pt-pt'
TIME_ZONE     = 'Europe/Lisbon'
USE_I18N      = True
USE_TZ        = True

STATIC_URL   = '/static/'
STATIC_ROOT  = BASE_DIR / 'staticfiles'
_STATIC_DIR = BASE_DIR / 'static'
STATICFILES_DIRS = [_STATIC_DIR] if _STATIC_DIR.exists() else []

MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

STORAGES = {
    'default':     {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
}

# S3 / Cloudflare R2 — activated when AWS_STORAGE_BUCKET_NAME env var is set
_S3_BUCKET = os.environ.get('AWS_STORAGE_BUCKET_NAME')
if _S3_BUCKET:
    STORAGES['default']      = {'BACKEND': 'storages.backends.s3.S3Storage'}
    AWS_ACCESS_KEY_ID        = os.environ.get('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY    = os.environ.get('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME  = _S3_BUCKET
    AWS_S3_REGION_NAME       = os.environ.get('AWS_S3_REGION_NAME', 'eu-west-1')
    AWS_S3_FILE_OVERWRITE    = False
    AWS_DEFAULT_ACL          = None
    _R2 = os.environ.get('AWS_S3_ENDPOINT_URL')
    if _R2:
        AWS_S3_ENDPOINT_URL = _R2
    # Public domain for media (e.g. R2 custom domain); otherwise signed URLs are generated
    _S3_DOMAIN = os.environ.get('AWS_S3_CUSTOM_DOMAIN')
    if _S3_DOMAIN:
        AWS_S3_CUSTOM_DOMAIN = _S3_DOMAIN
        AWS_QUERYSTRING_AUTH = False

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

EMAIL_BACKEND      = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST         = 'smtp.resend.com'
# Railway blocks outbound 587/465; Resend also accepts STARTTLS on 2587
EMAIL_PORT         = int(os.environ.get('EMAIL_PORT', '2587'))
EMAIL_TIMEOUT      = 20
EMAIL_USE_TLS      = True
EMAIL_HOST_USER    = 'resend'
EMAIL_HOST_PASSWORD = os.environ.get('RESEND_API_KEY', '')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'noreply@fogobom.com')
ADMIN_EMAIL        = os.environ.get('ADMIN_EMAIL', '')

# Password reset links expire after 2 hours
PASSWORD_RESET_TIMEOUT = 2 * 60 * 60

# CARTO raster basemaps — key removes the "API key required" watermark
CARTO_API_KEY      = os.environ.get('CARTO_API_KEY', '')
# MapTiler terrain tiles (slope/aspect on the weather page)
MAPTILER_API_KEY   = os.environ.get('MAPTILER_API_KEY', '')

# GDAL/GEOS — set via ENV in Dockerfile
# GDAL_LIBRARY_PATH = '/usr/lib/x86_64-linux-gnu/libgdal.so'
# GEOS_LIBRARY_PATH = '/usr/lib/x86_64-linux-gnu/libgeos_c.so'
