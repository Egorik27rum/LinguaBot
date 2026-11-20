from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: List[int]
    GROUP_ID: int
    POLZA_API_KEY: str | None = None
    STUDENT_BOT_TOKEN: str | None = None
    # Потеря ключа означает потерю секретов. Без ключа секреты хранятся открыто (совместимость).
    SETTINGS_KEY: str | None = None
    RETENTION_DAYS: int = 90
    DB_URL: str = 'sqlite+aiosqlite:///./lingua_data.db'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


config = Settings()
