from sqlalchemy import create_engine, Column, Integer, String, select, Index, DateTime, Enum    
from sqlalchemy.orm import declarative_base, Session
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

class ChatHistory(Base):
    __tablename__ = 'chat_history'
    
    id = Column(Integer, primary_key=True)
    chat_id = Column(String, nullable=False, index=True)  # UUID for chat session/thread
    user_name = Column(String, nullable=False, index=True)  # From get_current_user_name()
    message_type = Column(Enum(MessageType), nullable=False)  # user or assistant
    message_content = Column(String, nullable=False)  # The actual message text
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    message_order = Column(Integer, nullable=False)  # Order within the chat session
    
    # Composite index for efficient querying of chat sessions
    __table_args__ = (
        Index('idx_chat_user_order', 'chat_id', 'user_name', 'message_order'),
    ) 
