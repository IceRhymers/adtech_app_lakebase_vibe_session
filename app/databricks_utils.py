from databricks.sdk import WorkspaceClient
import os

def get_workspace_client():
    profile = os.getenv("DATABRICKS_PROFILE", None)
    if profile is None:
        return WorkspaceClient()
    else:
        return WorkspaceClient(profile=profile)