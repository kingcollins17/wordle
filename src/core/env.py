import os
import json
import logging
from typing import Optional, Dict, Any
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Environment(BaseSettings):
    """
    Application Environment settings loaded via Pydantic BaseSettings.
    Loads settings from .env file and environment variables.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # MySQL config
    db_host: Optional[str] = Field(default=None, validation_alias="DB_HOST")
    db_port: int = Field(default=3306, validation_alias="DB_PORT")
    db_user: Optional[str] = Field(default=None, validation_alias="DB_USER")
    db_password: Optional[str] = Field(default="", validation_alias="DB_PASSWORD")
    db_name: Optional[str] = Field(default=None, validation_alias="DB_NAME")

    # Redis config (optional)
    redis_host: Optional[str] = Field(default=None, validation_alias="REDIS_HOST")
    redis_port: Optional[int] = Field(default=6379, validation_alias="REDIS_PORT")
    redis_db: Optional[int] = Field(default=0, validation_alias="REDIS_DB")
    redis_username: Optional[str] = Field(default="default", validation_alias="REDIS_USERNAME")
    redis_password: Optional[str] = Field(default="", validation_alias="REDIS_PASSWORD")
    redis_url: Optional[str] = Field(default=None, validation_alias="REDIS_URL")

    # Gemini AI config
    gemini_api_key: Optional[str] = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_api_url: Optional[str] = Field(default=None, validation_alias="GEMINI_API_URL")
    gemini_api_model: Optional[str] = Field(default=None, validation_alias="GEMINI_API_MODEL")

    # Firebase Service Account JSON string or file path
    firebase_credentials: Optional[str] = Field(
        default=None,
        validation_alias="FIREBASE_CREDENTIALS",
    )
    firebase_credentials_path: Optional[str] = Field(
        default=None,
        validation_alias="FIREBASE_CREDENTIALS_PATH",
    )

    def model_post_init(self, __context: Any) -> None:
        if not self.redis_url and self.redis_host:
            user_part = f"{self.redis_username}:{self.redis_password}@" if self.redis_password else ""
            self.redis_url = f"redis://{user_part}{self.redis_host}:{self.redis_port}"

    def get_firebase_config(self) -> Dict[str, Any]:
        """
        Load and return Firebase service account configuration dictionary.
        Prioritizes reading from FIREBASE_CREDENTIALS environment variable (JSON string),
        falling back to reading from a JSON file path if specified.
        """
        # 1. Check FIREBASE_CREDENTIALS string (JSON string from .env)
        if self.firebase_credentials and self.firebase_credentials.strip():
            cred_str = self.firebase_credentials.strip()
            if cred_str.startswith("{"):
                try:
                    return json.loads(cred_str)
                except Exception as e:
                    logger.warning(f"Failed to parse FIREBASE_CREDENTIALS JSON string directly: {e}")

        # 2. Fallback to reading JSON from file if path is specified or exists in workspace
        paths_to_check = [
            self.firebase_credentials_path,
            "wordle-93ae2-firebase-adminsdk-fbsvc-2166f22eb4.json",
            "serviceAccountKey.json",
        ]
        for path in paths_to_check:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)

        raise FileNotFoundError(
            "Firebase credentials not found in FIREBASE_CREDENTIALS env variable or JSON file."
        )

    def get_mysql_config(self) -> dict:
        return {
            "host": self.db_host,
            "port": self.db_port,
            "user": self.db_user,
            "password": self.db_password,
            "db": self.db_name,
        }

    def get_gemini_config(self) -> dict:
        return {
            "api_key": self.gemini_api_key,
            "api_url": self.gemini_api_url,
            "model": self.gemini_api_model,
        }

    def get_redis_config(self) -> dict:
        return {
            "host": self.redis_host,
            "port": self.redis_port,
            "db": self.redis_db,
            "username": self.redis_username,
            "password": self.redis_password,
            "url": self.redis_url,
        }



    def __str__(self):
        return (
            f"MySQL -> Host: {self.db_host}, Port: {self.db_port}, User: {self.db_user}, DB: {self.db_name}\n"
            f"Redis -> Host: {self.redis_host}, Port: {self.redis_port}, URL: {self.redis_url}\n"
            f"Firebase Credentials -> {'set in env' if self.firebase_credentials else 'not set'}"
        )


# Global environment instance
_global_env: Environment = Environment()
APP_CONFIG = _global_env


def get_env() -> Environment:
    """FastAPI Dependency to retrieve Environment settings."""
    return _global_env


get_environment = get_env


def initialize_environment() -> Environment:
    global _global_env, APP_CONFIG
    _global_env = Environment()
    APP_CONFIG = _global_env
    return _global_env


def reset_environment():
    global _global_env, APP_CONFIG
    _global_env = Environment()
    APP_CONFIG = _global_env



