import os
from typing import Optional
from dotenv import load_dotenv


class Environment:
    def __init__(self, dotenv_path=".env"):
        load_dotenv(dotenv_path)

        # MySQL config
        self.db_host = os.getenv("DB_HOST")
        self.db_port = int(os.getenv("DB_PORT", 3306))
        self.db_user = os.getenv("DB_USER")
        self.db_password = os.getenv("DB_PASSWORD")
        self.db_name = os.getenv("DB_NAME")

        # Redis config
        self.redis_host = os.getenv("REDIS_HOST")
        self.redis_port = int(os.getenv("REDIS_PORT", 6379))
        self.redis_db = int(os.getenv("REDIS_DB", 0))
        self.redis_username = os.getenv("REDIS_USERNAME", "default")
        self.redis_password = os.getenv("REDIS_PASSWORD")
        # Construct REDIS_URL if not provided
        default_url = (
            f"redis://{self.redis_username}:{self.redis_password}"
            f"@{self.redis_host}:{self.redis_port}"
        )
        self.redis_url = os.getenv("REDIS_URL", default=default_url)

        # Gemini AI config
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.gemini_api_url = os.getenv("GEMINI_API_URL")
        self.gemini_api_model = os.getenv("GEMINI_API_MODEL")

    def __str__(self):
        return (
            f"MySQL -> Host: {self.db_host}, Port: {self.db_port}, User: {self.db_user}, "
            f"Password: {self.db_password}, DB: {self.db_name}\n"
            f"Redis -> Host: {self.redis_host}, Port: {self.redis_port}, DB: {self.redis_db}, "
            f"User: {self.redis_username}, Password: {self.redis_password}, URL: {self.redis_url}\n"
            f"Gemini -> API Key: {'set' if self.gemini_api_key else 'not set'}, "
            f"URL: {self.gemini_api_url}, Model: {self.gemini_api_model}"
        )

    def get_mysql_config(self) -> dict:
        """Get MySQL configuration as a dictionary."""
        return {
            "host": self.db_host,
            "port": self.db_port,
            "user": self.db_user,
            "password": self.db_password,
            "db": self.db_name,
        }

    def validate(self) -> bool:
        """Validate that all required environment variables are set."""
        required_vars = [
            self.db_host,
            self.db_user,
            self.db_password,
            self.db_name,
            self.redis_host,
            self.redis_password,
            # Add gemini_api_key only if you want it to be required
            # self.gemini_api_key
        ]
        return all(var is not None for var in required_vars)

    def get_gemini_config(self) -> dict:
        """Get Gemini configuration as a dictionary."""
        return {
            "api_key": self.gemini_api_key,
            "api_url": self.gemini_api_url,
            "model": self.gemini_api_model,
        }

    def get_redis_config(self) -> dict:
        """Get Redis configuration as a dictionary."""
        return {
            "host": self.redis_host,
            "port": self.redis_port,
            "db": self.redis_db,
            "username": self.redis_username,
            "password": self.redis_password,
            "url": self.redis_url,
        }


# Global environment instance
_global_env: Optional[Environment] = None


def initialize_environment(dotenv_path: str = ".env") -> Environment:
    """
    Initialize the global environment instance.

    Args:
        dotenv_path: Path to the .env file

    Returns:
        Environment: The initialized environment instance

    Raises:
        ValueError: If required environment variables are missing
    """
    global _global_env

    _global_env = Environment(dotenv_path)

    if not _global_env.validate():
        raise ValueError(
            "Missing required environment variables. Please check your .env file."
        )

    return _global_env


def get_environment() -> Environment:
    """
    Dependency injection function to get the global environment instance.

    Returns:
        Environment: The global environment instance

    Raises:
        RuntimeError: If environment hasn't been initialized
    """
    if _global_env is None:
        raise RuntimeError(
            "Environment not initialized. Call initialize_environment() first."
        )

    return _global_env


def get_environment_or_default(dotenv_path: str = ".env") -> Environment:
    """
    Get the global environment instance or create a default one.
    This is useful for cases where you want automatic initialization.

    Args:
        dotenv_path: Path to the .env file (used only if not already initialized)

    Returns:
        Environment: The environment instance
    """
    global _global_env

    if _global_env is None:
        _global_env = Environment(dotenv_path)

    return _global_env


# Alternative dependency function that auto-initializes
def get_env() -> Environment:
    """
    Shorter alias for dependency injection with auto-initialization.

    Returns:
        Environment: The environment instance
    """
    return get_environment_or_default()


def reset_environment():
    """
    Reset the global environment instance.
    Useful for testing or reloading configuration.
    """
    global _global_env
    _global_env = None
