import logging

from sqlalchemy import select

from database.engine import async_session
from database.models import Setting
from services.crypto import SecretDecryptError, decrypt_value, encrypt_value, is_encrypted

logger = logging.getLogger(__name__)

# Ключи, значения которых хранятся в БД в зашифрованном виде
SECRET_KEYS = {'polza_api_key'}


async def _read_raw(key: str) -> str | None:
    async with async_session() as session:
        return await session.scalar(select(Setting.value).where(Setting.key == key))


async def _write_raw(key: str, value: str) -> None:
    async with async_session() as session:
        obj = await session.get(Setting, key)
        if obj:
            obj.value = value
        else:
            session.add(Setting(key=key, value=value))
        await session.commit()


async def get_setting(key: str) -> str | None:
    raw = await _read_raw(key)
    if raw is None or key not in SECRET_KEYS:
        return raw
    try:
        return decrypt_value(raw)
    except SecretDecryptError as exc:
        # Бот продолжает работать: ключ считается не заданным, его можно ввести заново
        logger.error('Секрет %s не прочитан: %s. Задайте его заново в настройках', key, exc)
        return None


async def set_setting(key: str, value: str) -> None:
    stored = encrypt_value(value) if key in SECRET_KEYS else value
    await _write_raw(key, stored)


async def migrate_secrets() -> int:
    '''Однократно шифрует уже сохранённые секреты. Повторный запуск ничего не меняет.
    Возвращает количество перезаписанных значений.
    '''
    migrated = 0
    for key in SECRET_KEYS:
        raw = await _read_raw(key)
        if not raw or is_encrypted(raw):
            continue
        encrypted = encrypt_value(raw)
        if encrypted != raw:
            await _write_raw(key, encrypted)
            migrated += 1
    return migrated
