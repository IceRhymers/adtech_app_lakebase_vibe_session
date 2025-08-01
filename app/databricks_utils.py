from databricks.sdk import WorkspaceClient
import streamlit as st
import os

def get_workspace_client():
    """
    Get a workspace client for the current user.
    Needed because when using `databricks apps run-local` you can't use the default credential chain, works fine for the deployed app.
    """
    profile = os.getenv("DATABRICKS_PROFILE", None)
    if profile is None:
        return WorkspaceClient()
    else:
        return WorkspaceClient(profile=profile)
    
def get_current_user_name() -> str:
    """Get the current user's display name"""
    # Check if we're in Databricks by looking for the forwarded access token
    user_token = st.context.headers.get('X-Forwarded-Access-Token')
    
    if user_token:
        # We're deployed to Databricks, try using the forwarded token first
        try:
            databricks_client = WorkspaceClient(token=user_token, auth_type="pat")
            user_info = databricks_client.current_user.me()
            return user_info.user_name
        except Exception as token_error:
            # Token failed (insufficient scopes, invalid token, etc.), fall back to global client
            user_info = get_workspace_client().current_user.me()
            return user_info.user_name
    else:
        # Local development, use the global client
        user_info = get_workspace_client().current_user.me()
        return user_info.user_name
        