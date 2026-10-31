"""
Core platform configuration settings using Pydantic Settings.
Loads configuration from environment variables with fallback defaults for development.
"""
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Multi-Tenant Cloud IoT Platform"
    PROJECT_VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True

    # Database Configuration
    # Uses SQLite in development if POSTGRES_URL is not set, or PostgreSQL in staging/production
    DATABASE_URL: str = "sqlite:///./iot_platform_dev.db"
    DATABASE_ECHO: bool = False

    # Security & Tokens
    SECRET_KEY: str = "dev-insecure-secret-key-change-in-production-min-32-bytes!"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"

    # MQTT Gateway Configuration
    MQTT_BROKER_HOST: str = "localhost"
    MQTT_BROKER_PORT: int = 8883
    MQTT_CLIENT_ID: str = "cloud_platform_gateway"
    MQTT_TLS_ENABLED: bool = True

    # Initial Manufacturer Admin Seed Credentials
    SUPERADMIN_USERNAME: str = "admin"
    SUPERADMIN_EMAIL: str = "admin@manufacturer.local"
    SUPERADMIN_PASSWORD: str = "Admin@SecurePlatform2026!"

    # Razorpay Payment Gateway Configuration (Test / Development Mode)
    RAZORPAY_KEY_ID: str = "rzp_test_placeholder"
    RAZORPAY_KEY_SECRET: str = "placeholder_secret"
    RAZORPAY_WEBHOOK_SECRET: str = "placeholder_webhook_secret"
    RAZORPAY_CURRENCY: str = "INR"
    RAZORPAY_UPI_VPA: str = "gtech282722.rzp@rxairtel"
    RAZORPAY_AUTO_CAPTURE: bool = True
    RAZORPAY_TEST_MODE: bool = True
    OFFLINE_DISPENSE_HOLD_MINUTES: int = 60
    ORDER_DISPENSE_TIMEOUT_SECONDS: int = 300

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="allow",
    )


settings = Settings()
