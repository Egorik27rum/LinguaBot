'''Шифрование секретов (Fernet) для таблицы settings и configs/bots.json.

Зашифрованные значения начинаются с префикса 'enc:'. Значения без префикса считаются
открытыми (старые данные) и читаются как есть. Ключ берётся из SETTINGS_KEY.
Ни ключ, ни значения в логи не выводятся.
'''
import logging

from cryptography.fernet import Fernet, InvalidToken

from core.config import config

logger = logging.getLogger(__name__)

PREFIX = 'enc:'

_cached: tuple[str, Fernet] | None = None
_warned_no_key = False


class SecretDecryptError(Exception):
    '''Значение зашифровано, но его нельзя расшифровать: нет SETTINGS_KEY или ключ неверный.'''


def is_encrypted(value: str) -> bool:
    return value.startswith(PREFIX)


def _fernet() -> Fernet | None:
    global _cached, _warned_no_key
    key = (config.SETTINGS_KEY or '').strip()
    if not key:
        if not _warned_no_key:
            logger.warning('SETTINGS_KEY не задан в .env: секреты хранятся без шифрования. Запустите install.bat')
            _warned_no_key = True
        return None
    if _cached is None or _cached[0] != key:
        try:
            _cached = (key, Fernet(key.encode('ascii')))
        except (ValueError, TypeError, UnicodeError) as exc:
            # Молча писать открытый текст при неверном ключе нельзя
            raise RuntimeError(
                'SETTINGS_KEY имеет неверный формат. Исправьте .env или запустите install.bat заново'
            ) from exc
    return _cached[1]


def encrypt_value(plain: str) -> str:
    if not plain or is_encrypted(plain):
        return plain
    fernet = _fernet()
    if fernet is None:
        return plain
    return PREFIX + fernet.encrypt(plain.encode('utf-8')).decode('ascii')


def decrypt_value(token: str) -> str:
    '''Открытые значения возвращаются как есть. Нерасшифруемое значение вызывает SecretDecryptError:
    возвращать шифротекст нельзя, его примут за токен или ключ.
    '''
    if not token or not is_encrypted(token):
        return token
    fernet = _fernet()
    if fernet is None:
        raise SecretDecryptError('SETTINGS_KEY не задан, зашифрованное значение недоступно')
    try:
        return fernet.decrypt(token[len(PREFIX):].encode('ascii')).decode('utf-8')
    except (InvalidToken, UnicodeError) as exc:
        raise SecretDecryptError('неверный SETTINGS_KEY или повреждённые данные') from exc
