from databricks.sdk import WorkspaceClient
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