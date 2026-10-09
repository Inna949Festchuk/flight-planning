"""Django settings для GeoScan Planner."""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR.parent / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "geoscan-planner-dev-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "True") == "True"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
    "rest_framework",
    "rest_framework_gis",
    "corsheaders",
    "drf_spectacular",
    "users",
    "survey",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": os.environ.get("POSTGRES_DB", "geoscan_planner"),
        "USER": os.environ.get("POSTGRES_USER", "geoscan"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "geoscan"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

AUTH_USER_MODEL = "users.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 4}},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR.parent / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- DRF ---
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "survey.auth_internal.InternalTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "GeoScan Planner API",
    "DESCRIPTION": (
        "Сервис планирования и распределения беспилотных авиационных работ. "
        "MILP-оптимизация, два критерия (мин. время / мин. суммарный налёт), "
        "проверка запретов, энергии и сближений."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# --- JWT ---
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# --- CORS ---
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    "http://localhost:80",
    "http://127.0.0.1:80",
]

# --- Celery ---
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = os.environ.get("CELERY_TASK_ALWAYS_EAGER", "False") == "True"

# --- LLM (Qwen через OpenAI-совместимый API) ---
LLM_API_BASE_URL = os.environ.get("LLM_API_BASE_URL", "https://routerai.ru/api/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen/qwen3.7-plus")
LLM_REQUEST_TIMEOUT = int(os.environ.get("LLM_REQUEST_TIMEOUT", "180"))

# --- Внутренний токен для MCP-сервера ---
INTERNAL_API_TOKEN = os.environ.get("INTERNAL_API_TOKEN", "geoscan-internal-mcp-token")

# --- Параметры алгоритма (настраиваемые пороги сценария) ---
PLANNING = {
    "ENERGY_RESERVE": 0.2,  # безопасный остаток батареи (FR-18)
    "MAX_SORTIES_PER_UAV": 2,  # вылетов на БВС (FR-11)
    "RECHARGE_MIN": 10,  # замена АКБ между вылетами, мин (FR-11)
    "SIDE_OVERLAP": 0.5,  # межгалсовое перекрытие (TЗ: мин. 50%)
    "FRONT_OVERLAP": 0.6,  # продольное перекрытие
    "TURN_TIME_S": 8,  # разворот между галсами, с
    "CLIMB_TIME_MIN": 2,  # набор/сброс высоты, мин
    "ROUTE_CORRIDOR_FACTOR": 1.15,  # поправка на коридор вместо прямой
    "MAX_ALTITUDE_M": 3000,  # предельная высота полёта БВС, м
    "MIN_SEPARATION_M": 300,  # порог опасного сближения, м (FR-17)
    "CONFLICT_TIME_STEP_S": 10,  # шаг дискретной проверки сближений, с
    "MIN_SAMPLE_STEP_S": 2,  # минимальный шаг дискретизации
}

DATA_DIR = BASE_DIR / "geo_processing" / "data"
