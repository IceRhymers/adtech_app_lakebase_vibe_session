import os
import streamlit as st
import uuid
from datetime import datetime
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
from sqlalchemy.orm import Session
from sqlalchemy import desc
from models import ChatHistory, MessageType, Base
from lakebase import get_engine
from databricks_utils import get_workspace_client, get_current_user_name

# Set page config first - must be the first Streamlit command
st.set_page_config(
    page_title="AI Chatbot",
    page_icon="🤖",
    layout="wide"
)

# Initialize Databricks client
client: WorkspaceClient = get_workspace_client()

# Get database connection
db_name = os.getenv("LAKEBASE_DB_NAME", "vibe-session-db")
engine = get_engine(client, db_name)

# Get current user
current_user = get_current_user_name()

# Initialize session state
if 'current_chat_id' not in st.session_state:
    st.session_state.current_chat_id = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'chat_messages' not in st.session_state:
    st.session_state.chat_messages = []

def get_user_chats():
    """Get all chat sessions for the current user"""
    with Session(engine) as session:
        # Get the latest created_at for each chat_id
        from sqlalchemy import func
        subquery = session.query(
            ChatHistory.chat_id,
            func.max(ChatHistory.created_at).label('latest_created_at')
        ).filter(
            ChatHistory.user_name == current_user
        ).group_by(ChatHistory.chat_id).subquery()
        
        # Get chat_ids ordered by the latest created_at
        chats = session.query(subquery.c.chat_id).order_by(
            desc(subquery.c.latest_created_at)
        ).all()
        
        return [chat[0] for chat in chats]

def load_chat_history(chat_id: str):
    """Load chat history for a specific chat session"""
    with Session(engine) as session:
        messages = session.query(ChatHistory).filter(
            ChatHistory.chat_id == chat_id,
            ChatHistory.user_name == current_user
        ).order_by(ChatHistory.message_order).all()
        return messages

def save_message(chat_id: str, message_type: MessageType, content: str, message_order: int):
    """Save a message to the database"""
    with Session(engine) as session:
        message = ChatHistory(
            chat_id=chat_id,
            user_name=current_user,
            message_type=message_type,
            message_content=content,
            message_order=message_order
        )
        session.add(message)
        session.commit()

def get_next_message_order(chat_id: str) -> int:
    """Get the next message order number for a chat"""
    with Session(engine) as session:
        last_message = session.query(ChatHistory).filter(
            ChatHistory.chat_id == chat_id,
            ChatHistory.user_name == current_user
        ).order_by(desc(ChatHistory.message_order)).first()
        return (last_message.message_order + 1) if last_message else 1

def generate_bot_response(messages: list[ChatMessage]) -> str:
    """Generate bot response using Databricks chat API with message history"""
    try:
        # Get the agent endpoint from environment variable
        agent_endpoint = os.getenv("AGENT_ENDPOINT")
        if not agent_endpoint:
            return "Error: AGENT_ENDPOINT environment variable not configured."
        
        # Use the workspace client to query the chat endpoint with message history
        response = client.serving_endpoints.query(
            name=agent_endpoint,
            messages=messages
        )
        
        return response.choices[0].message.content
            
    except Exception as e:
        return f"Error calling model serving endpoint: {str(e)}"

# Sidebar for chat management
st.sidebar.title("💬 Chat Sessions")
st.sidebar.markdown(f"**User:** {current_user}")

# New chat button
if st.sidebar.button("🆕 Start New Chat", type="primary"):
    new_chat_id = str(uuid.uuid4())
    st.session_state.current_chat_id = new_chat_id
    st.session_state.chat_history = []
    st.session_state.chat_messages = []
    st.rerun()

# List existing chats
user_chats = get_user_chats()
if user_chats:
    st.sidebar.subheader("📋 Your Chats")
    for i, chat_id in enumerate(user_chats):
        chat_label = f"Chat {i+1}"
        if st.sidebar.button(
            chat_label, 
            key=f"chat_{chat_id}",
            type="secondary" if chat_id != st.session_state.current_chat_id else "primary"
        ):
            st.session_state.current_chat_id = chat_id
            st.session_state.chat_history = load_chat_history(chat_id)
            # Reset and rebuild ChatMessages array for the new chat
            st.session_state.chat_messages = []
            for message in st.session_state.chat_history:
                role = ChatMessageRole.USER if message.message_type == MessageType.USER else ChatMessageRole.ASSISTANT
                st.session_state.chat_messages.append(
                    ChatMessage(role=role, content=message.message_content)
                )
            st.rerun()

# Main chat interface
st.title("🤖 AI Chatbot")

# Check if we have a current chat
if st.session_state.current_chat_id is None:
    st.info("👋 Welcome! Click 'Start New Chat' to begin a conversation.")
else:
    current_chat_id = st.session_state.current_chat_id
    
    # Load chat history if not already loaded
    if not st.session_state.chat_history:
        st.session_state.chat_history = load_chat_history(current_chat_id)
        # Convert database messages to ChatMessages
        st.session_state.chat_messages = []
        for message in st.session_state.chat_history:
            role = ChatMessageRole.USER if message.message_type == MessageType.USER else ChatMessageRole.ASSISTANT
            st.session_state.chat_messages.append(
                ChatMessage(role=role, content=message.message_content)
            )
    
    # Display chat history
    for message in st.session_state.chat_history:
        if message.message_type == MessageType.USER:
            with st.chat_message("user"):
                st.write(message.message_content)
        else:
            with st.chat_message("assistant"):
                st.write(message.message_content)
    
    # Chat input
    if prompt := st.chat_input("Type your message here..."):
        # Get next message order
        next_order = get_next_message_order(current_chat_id)
        
        # Save user message to database
        save_message(current_chat_id, MessageType.USER, prompt, next_order)
        
        # Add user message to ChatMessages array
        st.session_state.chat_messages.append(
            ChatMessage(role=ChatMessageRole.USER, content=prompt)
        )
        
        # Display user message
        with st.chat_message("user"):
            st.write(prompt)
        
        # Generate bot response using ChatMessages array
        bot_response = generate_bot_response(st.session_state.chat_messages)
        
        # Save bot response to database
        save_message(current_chat_id, MessageType.ASSISTANT, bot_response, next_order + 1)
        
        # Add assistant message to ChatMessages array
        st.session_state.chat_messages.append(
            ChatMessage(role=ChatMessageRole.ASSISTANT, content=bot_response)
        )
        
        # Display bot response
        with st.chat_message("assistant"):
            st.write(bot_response)
        
        # Refresh chat history from database
        st.session_state.chat_history = load_chat_history(current_chat_id)
        st.rerun()

# Add information panel
with st.expander("ℹ️ About this Chatbot"):
    st.markdown(f"""
    **Features:**
    - 💾 Full conversation history saved to database
    - 🧵 Multiple chat threads/sessions
    - 👤 User identification via Databricks
    - 🔄 Persistent conversations across sessions
    
    **Current User:** `{current_user}`
    
    **Current Chat ID:** `{st.session_state.current_chat_id or 'None'}`
    
    **How to use:**
    1. Click "Start New Chat" to begin a conversation
    2. Type messages in the chat input
    3. Switch between different chat sessions using the sidebar
    4. All conversations are automatically saved
    
    *Note: This is a simple echo bot. The response system can be enhanced with actual AI integration.*
    """)
