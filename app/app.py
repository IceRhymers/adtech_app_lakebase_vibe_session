import os
import streamlit as st
from databricks.sdk import WorkspaceClient
from sqlalchemy.orm import Session
from models.config_table import ConfigKV, Base
from lakebase import get_engine
from databricks_utils import get_workspace_client
import uuid

# Initialize Databricks client
client: WorkspaceClient = get_workspace_client()

# Get database connection
db_name = os.getenv("LAKEBASE_DB_NAME", "vibe-session-db")
engine = get_engine(client, db_name)

st.set_page_config(
    page_title="Key-Value Config Editor",
    page_icon="⚙️",
    layout="wide"
)

st.title("⚙️ Key-Value Configuration Editor")
st.markdown("Add, edit, and manage key-value pairs in your PostgreSQL database.")

# Initialize session state for form data
if 'editing_key' not in st.session_state:
    st.session_state.editing_key = None
if 'editing_value' not in st.session_state:
    st.session_state.editing_value = ""

# Function to load all key-value pairs
def load_config_pairs():
    with Session(engine) as session:
        pairs = session.query(ConfigKV).all()
        return {pair.key: pair.value for pair in pairs}

# Function to save a key-value pair
def save_key_value(key, value):
    with Session(engine) as session:
        # Check if key already exists
        existing = session.query(ConfigKV).filter(ConfigKV.key == key).first()
        if existing:
            existing.value = value
        else:
            new_pair = ConfigKV(key=key, value=value)
            session.add(new_pair)
        session.commit()
    st.success(f"✅ Saved: {key} = {value}")

# Function to delete a key-value pair
def delete_key_value(key):
    with Session(engine) as session:
        pair = session.query(ConfigKV).filter(ConfigKV.key == key).first()
        if pair:
            session.delete(pair)
            session.commit()
            st.success(f"🗑️ Deleted: {key}")

# Load existing pairs
config_pairs = load_config_pairs()

# Create two columns
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("➕ Add New Key-Value Pair")
    
    with st.form("add_pair_form"):
        new_key = st.text_input("Key", key="new_key_input")
        new_value = st.text_input("Value", key="new_value_input")
        submit_button = st.form_submit_button("Save Pair")
        
        if submit_button and new_key and new_value:
            if new_key in config_pairs:
                st.error(f"❌ Key '{new_key}' already exists!")
            else:
                save_key_value(new_key, new_value)
                st.rerun()

with col2:
    st.subheader("✏️ Edit Existing Pair")
    
    if config_pairs:
        selected_key = st.selectbox(
            "Select key to edit",
            options=list(config_pairs.keys()),
            key="edit_select"
        )
        
        if selected_key:
            current_value = config_pairs[selected_key]
            
            with st.form("edit_pair_form"):
                edited_value = st.text_input(
                    "New Value",
                    value=current_value,
                    key="edit_value_input"
                )
                
                col_edit, col_delete = st.columns(2)
                
                with col_edit:
                    if st.form_submit_button("Update"):
                        if edited_value != current_value:
                            save_key_value(selected_key, edited_value)
                            st.rerun()
                        else:
                            st.info("No changes made.")
                
                with col_delete:
                    if st.form_submit_button("🗑️ Delete", type="secondary"):
                        delete_key_value(selected_key)
                        st.rerun()
    else:
        st.info("No key-value pairs found. Add some using the form on the left!")

# Display all current pairs
st.subheader("📋 Current Key-Value Pairs")
if config_pairs:
    # Reload to get latest data
    config_pairs = load_config_pairs()
    
    # Create a nice table display
    pairs_data = []
    for key, value in config_pairs.items():
        pairs_data.append({
            "Key": key,
            "Value": value,
            "Actions": f"Edit/Delete above"
        })
    
    st.dataframe(
        pairs_data,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Key": st.column_config.TextColumn("Key", width="medium"),
            "Value": st.column_config.TextColumn("Value", width="large"),
            "Actions": st.column_config.TextColumn("Actions", width="small")
        }
    )
    
    st.info(f"📊 Total pairs: {len(config_pairs)}")
else:
    st.info("No key-value pairs configured yet. Start by adding some above!")

# Add some helpful information
with st.expander("ℹ️ How to use this app"):
    st.markdown("""
    **This app allows you to:**
    - ✅ Add new key-value pairs
    - ✏️ Edit existing values
    - 🗑️ Delete key-value pairs
    - 📋 View all current pairs
    
    **Features:**
    - Data is automatically saved to PostgreSQL
    - Duplicate keys are prevented
    - Real-time updates
    - Clean, intuitive interface
    """)
