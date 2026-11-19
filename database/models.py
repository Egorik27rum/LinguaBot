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
    topic_id = Column(Integer, nullable=True)  # ID личного топика в группе
    joined_at = Column(DateTime, default=utcnow)
    attempts = relationship('Attempt', back_populates='student')


class Task(Base):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    content = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class Attempt(Base):
    __tablename__ = 'attempts'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'))
    task_id = Column(Integer, ForeignKey('tasks.id'))
    score = Column(Float)
    transcription = Column(String)
    created_at = Column(DateTime, default=utcnow)
    student = relationship('Student', back_populates='attempts')


class ChatMessage(Base):
    '''История диалога ученика с нейросетью в ученическом боте.'''
    __tablename__ = 'chat_messages'
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey('students.id'), nullable=False, index=True)
    role = Column(String, nullable=False)  # 'user' или 'assistant'
    content = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)
