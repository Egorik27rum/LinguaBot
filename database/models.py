from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = 'settings'
    key = Column(String, primary_key=True)
    value = Column(String)


class Student(Base):
    __tablename__ = 'students'
    id = Column(Integer, primary_key=True)
    tg_id = Column(Integer, unique=True, nullable=False)
    username = Column(String)
    full_name = Column(String)
    topic_id = Column(Integer, nullable=True)
    joined_at = Column(DateTime, default=utcnow)
    attempts = relationship('Attempt', back_populates='student')


class Task(Base):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    content = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class Goal(Base):
    '''Цель диалога: то, чего ученик должен достичь в разговоре с нейросетью.'''
    __tablename__ = 'goals'
    id = Column(Integer, primary_key=True)
    text = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class DialogSession(Base):
    '''Один диалог ученика по заданию. Лимит, цель и режим фиксируются при старте.'''
    __tablename__ = 'dialog_sessions'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey('tasks.id'), nullable=True)
    goal_id = Column(Integer, ForeignKey('goals.id'), nullable=True)
    goal_mode = Column(String, nullable=True)
    reply_limit = Column(Integer, nullable=False, default=8)
    replies_used = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default='active', index=True)
    goal_result = Column(String, nullable=True)
    feedback = Column(String, nullable=True)
    # Итог, как он показан ученику (build_report). Нужен истории диалога в топике
    report = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime, nullable=True)


class Attempt(Base):
    __tablename__ = 'attempts'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'))
    task_id = Column(Integer, ForeignKey('tasks.id'))
    session_id = Column(Integer, ForeignKey('dialog_sessions.id'), nullable=True)
    score = Column(Float)
    transcription = Column(String)
    created_at = Column(DateTime, default=utcnow)
    student = relationship('Student', back_populates='attempts')


class ChatMessage(Base):
    '''История общения ученика с нейросетью. session_id заполнен для сообщений диалога по заданию.'''
    __tablename__ = 'chat_messages'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey('dialog_sessions.id'), nullable=True, index=True)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class TopicMessage(Base):
    '''Сообщения топика ученика, относящиеся к диалогу: ссылки на сообщения Telegram.

    Сами данные диалога лежат в chat_messages. Удаление строк отсюда не влияет на историю в базе.
    '''
    __tablename__ = 'topic_messages'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False, index=True)
    session_id = Column(Integer, ForeignKey('dialog_sessions.id'), nullable=False, index=True)
    message_id = Column(Integer, nullable=False)
    kind = Column(String, nullable=False, default='text')
    created_at = Column(DateTime, default=utcnow)
