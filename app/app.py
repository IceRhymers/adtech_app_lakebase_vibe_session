import os
import streamlit as st
import uuid
import pandas as pd
import json
from datetime import datetime
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import ChatMessage, ChatMessageRole
from sqlalchemy.orm import Session
from sqlalchemy import desc
from models import ChatHistory, MessageType, Base, ChatSession
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
        # Query ChatSession directly, ordered by updated_at (most recent first)
        chat_sessions = session.query(ChatSession).filter(
            ChatSession.user_name == current_user
        ).order_by(desc(ChatSession.updated_at)).all()
        
        return chat_sessions

def create_new_chat_session(chat_id: str):
    """Create a new chat session"""
    with Session(engine) as session:
        chat_session = ChatSession(
            id=chat_id,
            user_name=current_user,
            title=None,  # Will be generated later
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(chat_session)
        session.commit()
        return chat_session

def delete_chat_session(session_id: str):
    """Delete a chat session and all its messages (cascade delete)"""
    with Session(engine) as session:
        chat_session = session.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_name == current_user  # Security: only delete own chats
        ).first()
        
        if chat_session:
            session.delete(chat_session)
            session.commit()
            return True
        return False

def update_session_timestamp(session_id: str):
    """Update the session's updated_at timestamp when new messages are added"""
    with Session(engine) as session:
        chat_session = session.query(ChatSession).filter(
            ChatSession.id == session_id,
            ChatSession.user_name == current_user
        ).first()
        
        if chat_session:
            chat_session.updated_at = datetime.utcnow()
            session.commit()

def generate_title_with_llama(context_text: str) -> str:
    """Generate a concise title using the Llama model endpoint"""
    try:
        # Create a focused prompt for title generation
        title_prompt = f"""Generate a concise title for this conversation in exactly 15 words or fewer. Return only the title, no quotes, no explanations:

{context_text}

Title:"""
        
        # Create message for the Llama endpoint
        messages = [ChatMessage(
            role=ChatMessageRole.USER,
            content=title_prompt
        )]
        
        # Convert to the format expected by the endpoint
        message_dicts = []
        for msg in messages:
            message_dicts.append({
                "role": msg.role.value,
                "content": msg.content
            })
        
        payload = {
            "messages": message_dicts,
            "max_tokens": 50,
            "temperature": 0.1  # Low temperature for consistent, focused output
        }
        
        payload_json = json.dumps(payload)
        
        # Use the Llama endpoint specifically for title generation
        response = client.api_client.do(
            method="POST",
            path="/serving-endpoints/databricks-meta-llama-3-3-70b-instruct/invocations",
            headers={"Content-Type": "application/json"},
            data=payload_json
        )
        
        # Extract the response text
        if isinstance(response, list) and len(response) > 0:
            title = response[0].strip()
        elif isinstance(response, dict) and 'choices' in response:
            title = response['choices'][0]['message']['content'].strip()
        else:
            title = str(response).strip()
        
        # Clean up the title
        title = title.strip().strip('"').strip("'").strip()
        
        # Remove common prefixes that might appear
        prefixes_to_remove = ["Title:", "title:", "TITLE:", "Generated title:", "The title is:", "Here's a title:"]
        for prefix in prefixes_to_remove:
            if title.lower().startswith(prefix.lower()):
                title = title[len(prefix):].strip()
        
        # Ensure it's not too long (15 words max)
        words = title.split()
        if len(words) > 15:
            title = " ".join(words[:15])
        
        # Limit character length as well
        if len(title) > 60:
            title = title[:57] + "..."
        
        return title if title else "New Chat"
        
    except Exception as e:
        print(f"Error generating title with Llama: {str(e)}")
        return "New Chat"

def generate_chat_title(session_id: str) -> str:
    """Generate an AI-powered title for a chat session"""
    try:
        # Get first few messages for context
        with Session(engine) as session:
            messages = session.query(ChatHistory).filter(
                ChatHistory.chat_id == session_id,
                ChatHistory.user_name == current_user
            ).order_by(ChatHistory.message_order).limit(4).all()  # First 2 exchanges
            
            if len(messages) < 2:
                return "New Chat"  # Not enough context
            
            # Build context for title generation
            context = []
            for msg in messages:
                role = "User" if msg.message_type == MessageType.USER else "Assistant"
                context.append(f"{role}: {msg.message_content[:150]}...")  # Limit length
            
            context_text = "\n".join(context)
            
            # Use the new Llama-based title generation
            title = generate_title_with_llama(context_text)
            
            # Update the session with the new title
            chat_session = session.query(ChatSession).filter(
                ChatSession.id == session_id,
                ChatSession.user_name == current_user
            ).first()
            
            if chat_session:
                chat_session.title = title
                chat_session.updated_at = datetime.utcnow()
                session.commit()
            
            return title
            
    except Exception as e:
        # Fallback to first message or generic title
        try:
            with Session(engine) as session:
                first_message = session.query(ChatHistory).filter(
                    ChatHistory.chat_id == session_id,
                    ChatHistory.user_name == current_user,
                    ChatHistory.message_type == MessageType.USER
                ).order_by(ChatHistory.message_order).first()
                
                if first_message:
                    fallback_title = first_message.message_content[:30] + "..." if len(first_message.message_content) > 30 else first_message.message_content
                    
                    # Update session with fallback title
                    chat_session = session.query(ChatSession).filter(
                        ChatSession.id == session_id,
                        ChatSession.user_name == current_user
                    ).first()
                    
                    if chat_session:
                        chat_session.title = fallback_title
                        session.commit()
                    
                    return fallback_title
        except:
            pass
        
        return "New Chat"

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
    
    # Update the session timestamp
    update_session_timestamp(chat_id)
    
    # Generate title after sufficient messages (e.g., after 2nd exchange)
    if message_order >= 3:  # After user, assistant, user messages
        try:
            # Check if session already has a title
            with Session(engine) as session:
                chat_session = session.query(ChatSession).filter(
                    ChatSession.id == chat_id,
                    ChatSession.user_name == current_user
                ).first()
                
                if chat_session and not chat_session.title:
                    # Generate title in background (non-blocking)
                    generate_chat_title(chat_id)
        except:
            pass  # Don't let title generation break the message saving

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
        
        system_prompt = """
        You are a helpful assistant that can answer questions and help with tasks, you are also able to search the chat history for relevant information. 
        If the user asks a question that is not related to the chat history, you shouldn't mention you couldn't find anything related to the question.
        """
        
        # Convert ChatMessage objects to simple dictionaries
        message_dicts = []
        messages.insert(0, ChatMessage(role=ChatMessageRole.SYSTEM, content=system_prompt))
        for msg in messages:
            message_dicts.append({
                "role": msg.role.value,  # Convert enum to string
                "content": msg.content
            })
        
        # Create the payload structure expected by the agent
        # TODO: FIX

        payload = {
            "messages": message_dicts,
            "custom_inputs": {
                "filters": {
                    "user_name": current_user
                }
            }
        }

        payload_json = json.dumps(payload)
        
        # Use the workspace client to query the chat endpoint with dataframe records
        # response = client.serving_endpoints.query(
        #     name=agent_endpoint,
        #     inputs=payload_json
        # )

        response = client.api_client.do(
            method="POST",
            path=f"/serving-endpoints/{agent_endpoint}/invocations",
            headers={"Content-Type": "application/json"},
            data=payload_json
        )
        
        print(response)
        return response[0]
            
    except Exception as e:
        return f"Error calling model serving endpoint: {str(e)}"

# Sidebar for chat management
st.sidebar.title("💬 Chat Sessions")
st.sidebar.markdown(f"**User:** {current_user}")

# New chat button
if st.sidebar.button("🆕 Start New Chat", type="primary"):
    new_chat_id = str(uuid.uuid4())
    # Create the chat session first
    create_new_chat_session(new_chat_id)
    st.session_state.current_chat_id = new_chat_id
    st.session_state.chat_history = []
    st.session_state.chat_messages = []
    st.rerun()

# List existing chats
user_chats = get_user_chats()
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
                st.session_state.chat_history = load_chat_history(chat_session.id)
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
                if delete_chat_session(chat_to_delete):
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
