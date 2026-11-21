from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Mini App: публичный HTTPS-адрес (туннель или домен). Без него кнопка приложения не появится
    WEBAPP_URL: str | None = None
    # Адрес, на котором слушает встроенный сервер. Наружу его выводит туннель
    WEBAPP_HOST: str = '127.0.0.1'
    WEBAPP_PORT: int = 8088  # 0 — не запускать Mini App
    # Сколько секунд initData считается действительной
    WEBAPP_AUTH_MAX_AGE: int = 3600
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


config = Settings()
