from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: List[int]
    GROUP_ID: int
    POLZA_API_KEY: str | None = None  # резервный ключ, основной хранится в БД
    STUDENT_BOT_TOKEN: str | None = None  # токен бота для учеников (необязательно)
    DB_URL: str = 'sqlite+aiosqlite:///./lingua_data.db'
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


config = Settings()
