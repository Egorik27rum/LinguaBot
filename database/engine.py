from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from .models import Base
from core.config import config

engine = create_async_engine(
    config.DB_URL,
    echo=False,
    connect_args={"check_same_thread": False}
)

async_session = async_sessionmaker(engine, expire_on_commit=False)

MIGRATIONS = (
    ('chat_messages', 'session_id', 'INTEGER REFERENCES dialog_sessions(id)'),
    ('attempts', 'session_id', 'INTEGER REFERENCES dialog_sessions(id)'),
    ('dialog_sessions', 'report', 'TEXT'),
)
INDEXES = (
    'CREATE INDEX IF NOT EXISTS ix_chat_messages_session_id ON chat_messages (session_id)',
)


async def _migrate(conn) -> None:
    '''Добавляет недостающие nullable-колонки. Существующие данные не меняются.'''
    for table, column, ddl in MIGRATIONS:
        result = await conn.exec_driver_sql(f'PRAGMA table_info({table})')
        existing = {row[1] for row in result.fetchall()}
        if column not in existing:
            await conn.exec_driver_sql(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}')
    for statement in INDEXES:
        await conn.exec_driver_sql(statement)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
