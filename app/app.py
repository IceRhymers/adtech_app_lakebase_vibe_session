import os
import streamlit as st
import uuid
from datetime import datetime
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
from models import MessageType
from lakebase import get_engine
from databricks_utils import get_workspace_client, get_current_user_name
from services.chat_service import ChatService
from services.agent_service import AgentService

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

# Services
chat_service = ChatService(engine, current_user)
agent_service = AgentService()


# Sidebar for chat management
st.sidebar.title("💬 Chat Sessions")
st.sidebar.markdown(f"**User:** {current_user}")

# New chat button
if st.sidebar.button("🆕 Start New Chat", type="primary"):
    new_chat_id = str(uuid.uuid4())
    # Create the chat session first
    chat_service.create_new_chat_session(new_chat_id)
    st.session_state.current_chat_id = new_chat_id
    st.session_state.chat_history = []
    st.session_state.chat_messages = []
    st.rerun()

# List existing chats
user_chats = chat_service.get_user_chats()
if user_chats:
    st.sidebar.subheader("📋 Your Chats")
    for i, chat_session in enumerate(user_chats):
        # Create a nice display label with title and timestamp
        if chat_session.title:
            chat_label = chat_session.title
        else:
            chat_label = f"Chat {i+1}"
        
        # Format timestamp
        time_str = chat_session.updated_at.strftime("%m/%d %H:%M")
        display_label = f"{chat_label}"
        
        # Create columns for chat button and delete button
        col1, col2 = st.sidebar.columns([4, 1])
        
        with col1:
            if st.button(
                display_label, 
                key=f"chat_{chat_session.id}",
                type="secondary" if chat_session.id != st.session_state.current_chat_id else "primary",
                help=f"Last updated: {time_str}"
            ):
                st.session_state.current_chat_id = chat_session.id
                st.session_state.chat_history = chat_service.load_chat_history(chat_session.id)
                # Reset and rebuild ChatMessages array for the new chat
                st.session_state.chat_messages = []
                for message in st.session_state.chat_history:
                    role = ChatMessageRole.USER if message.message_type == MessageType.USER else ChatMessageRole.ASSISTANT
                    st.session_state.chat_messages.append(
                        ChatMessage(role=role, content=message.message_content)
                    )
                st.rerun()
        
        with col2:
            # Delete button with confirmation
            if st.button("🗑️", key=f"delete_{chat_session.id}", help="Delete this conversation"):
                # Use session state to track which chat is being deleted for confirmation
                st.session_state.confirm_delete = chat_session.id

# Handle delete confirmation
if hasattr(st.session_state, 'confirm_delete') and st.session_state.confirm_delete:
    chat_to_delete = st.session_state.confirm_delete
    
    # Find the chat session to get its title for the confirmation message
    session_to_delete = None
    for chat_session in user_chats:
        if chat_session.id == chat_to_delete:
            session_to_delete = chat_session
            break
    
    if session_to_delete:
        title = session_to_delete.title or "this chat"
        st.sidebar.error(f"⚠️ Delete '{title}'?")
        
        col1, col2 = st.sidebar.columns(2)
        with col1:
            if st.button("✅ Yes", key="confirm_yes"):
                # Perform the deletion
                if chat_service.delete_chat_session(chat_to_delete):
                    # If deleting current chat, reset to no chat
                    if st.session_state.current_chat_id == chat_to_delete:
                        st.session_state.current_chat_id = None
                        st.session_state.chat_history = []
                        st.session_state.chat_messages = []
                    
                    # Clear confirmation state
                    del st.session_state.confirm_delete
                    st.success("Chat deleted successfully!")
                    st.rerun()
                else:
                    st.error("Failed to delete chat")
        
        with col2:
            if st.button("❌ No", key="confirm_no"):
                # Cancel deletion
                del st.session_state.confirm_delete
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
        st.session_state.chat_history = chat_service.load_chat_history(current_chat_id)
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
        next_order = chat_service.get_next_message_order(current_chat_id)

        # Save user message + embedding atomically
        try:
            chat_service.save_message_with_embedding(current_chat_id, MessageType.USER, prompt, next_order)
        except Exception as e:
            st.error(f"Failed to save your message: {e}")
        else:
            # Add user message to ChatMessages array
            st.session_state.chat_messages.append(
                ChatMessage(role=ChatMessageRole.USER, content=prompt)
            )

            # Display user message
            with st.chat_message("user"):
                st.write(prompt)

            # Generate bot response using ChatMessages array
            bot_response = agent_service.generate_bot_response(current_user, st.session_state.chat_messages)

            # Save bot response + embedding atomically
            try:
                chat_service.save_message_with_embedding(current_chat_id, MessageType.ASSISTANT, bot_response, next_order + 1)
            except Exception as e:
                st.error(f"Failed to save assistant message: {e}")
            else:
                # Add assistant message to ChatMessages array
                st.session_state.chat_messages.append(
                    ChatMessage(role=ChatMessageRole.ASSISTANT, content=bot_response)
                )

                # Display bot response
                with st.chat_message("assistant"):
                    st.write(bot_response)

                # Refresh chat history from database
                st.session_state.chat_history = chat_service.load_chat_history(current_chat_id)
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
