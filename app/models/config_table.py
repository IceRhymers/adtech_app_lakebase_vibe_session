from sqlalchemy import create_engine, Column, Integer, String, select, Index, DateTime, Enum, ForeignKey
from sqlalchemy.orm import declarative_base, Session, relationship
import os
import enum
from datetime import datetime

Base = declarative_base()

class MessageType(enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"

class ConfigKV(Base):
    __tablename__ = 'config_kv'
    id = Column(Integer, primary_key=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(String, nullable=False)

class ChatSession(Base):
    __tablename__ = 'chat_sessions'
    
    id = Column(String, primary_key=True)  # UUID
    user_name = Column(String, nullable=False, index=True)
    title = Column(String, nullable=True)  # AI-generated or manual title
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    
    # Relationship to chat messages
    messages = relationship("ChatHistory", back_populates="session", cascade="all, delete-orphan")
    
    # Index for efficient user queries
    __table_args__ = (
        Index('idx_user_updated', 'user_name', 'updated_at'),
    )

class ChatHistory(Base):
    __tablename__ = 'chat_history'
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(String, ForeignKey('chat_sessions.id', ondelete='CASCADE'), nullable=False, index=True)  # References ChatSession.id
    user_name = Column(String, nullable=False, index=True)  # From get_current_user_name()
    message_type = Column(Enum(MessageType), nullable=False)  # user or assistant
    message_content = Column(String, nullable=False)  # The actual message text
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    message_order = Column(Integer, nullable=False)  # Order within the chat session
    
    # Relationship back to session
    session = relationship("ChatSession", back_populates="messages")

    # One-to-one relationship to embedding
    embedding = relationship("MessageEmbedding", back_populates="message", cascade="all, delete-orphan", uselist=False)
    
    # Composite index for efficient querying of chat sessions
    __table_args__ = (
        Index('idx_chat_user_order', 'chat_id', 'user_name', 'message_order'),
    ) 
