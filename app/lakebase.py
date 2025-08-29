from databricks.sdk import WorkspaceClient
import uuid
import os
import sys
import logging
from typing import Optional
from sqlalchemy import create_engine

def get_postgres_connection(
    client: WorkspaceClient,
    db_name: str,
    database_name: Optional[str] = "databricks_postgres"
) -> str:
    """
    Get PostgreSQL connection string using Databricks SDK.

    Args:
        client (WorkspaceClient): The Databricks workspace client.
        db_name (str): The name of the database instance.
        database_name (Optional[str], optional): The name of the database to connect to.
            Defaults to "databricks_postgres".

    Returns:
        str: SQLAlchemy-compatible PostgreSQL connection string.
    """
    database = client.database.get_database_instance(db_name)
    credentials = client.database.generate_database_credential(
        instance_names=[db_name],
        request_id=str(uuid.uuid4())
    )

    # Use POSTGRES_GROUP env var as username if set, otherwise use current user
    postgres_group = os.getenv('POSTGRES_GROUP')
    username = postgres_group if postgres_group else client.current_user.me().user_name

    database_info = {
        "host": database.read_write_dns,
        "port": "5432",
        "database": database_name,
        "username": username,
        "password": credentials.token,
        "ssl_mode": "require"
    }

    database_url = (
        f"postgresql://{database_info['username']}:{database_info['password']}"
        f"@{database_info['host']}:{database_info['port']}/"
        f"{database_info['database']}?sslmode={database_info['ssl_mode']}"
    )

    return database_url

def get_jdbc_url(
    client: WorkspaceClient,
    db_name: str,
    database_name: Optional[str] = "databricks_postgres"
) -> str:
    """
    Get JDBC URL for PostgreSQL connection using Databricks SDK.

    Args:
        client (WorkspaceClient): The Databricks workspace client.
        db_name (str): The name of the database instance.
        database_name (Optional[str], optional): The name of the database to connect to.
            Defaults to "databricks_postgres".

    Returns:
        str: JDBC-compatible PostgreSQL connection string.
    """
    logger = logging.getLogger(__name__)
    logger.debug(f"Attempting to get database instance: {db_name}")
    print(f"DEBUG: Attempting to get database instance: {db_name}", file=sys.stderr)
    
    database = client.database.get_database_instance(db_name)
    credentials = client.database.generate_database_credential(
        instance_names=[db_name],
        request_id=str(uuid.uuid4())
    )

    # Use POSTGRES_GROUP env var as username if set, otherwise use current user
    postgres_group = os.getenv('POSTGRES_GROUP')
    username = postgres_group if postgres_group else client.current_user.me().user_name

    database_info = {
        "host": database.read_write_dns,
        "port": "5432",
        "database": database_name,
        "username": username,
        "password": credentials.token,
        "ssl_mode": "require"
    }

    jdbc_url = (
        f"jdbc:postgresql://{database_info['host']}:{database_info['port']}/"
        f"{database_info['database']}?sslmode={database_info['ssl_mode']}"
        f"&user={database_info['username']}&password={database_info['password']}"
    )

    return jdbc_url

def get_engine(client: WorkspaceClient, db_name: str, database_name: Optional[str] = "databricks_postgres"):
    """
    Gets a SQLAlchemy engine for the specified Lakebase database.

    This function retrieves the connection URL for the given database from Lakebase and returns a SQLAlchemy engine instance.

    Args:
        client (WorkspaceClient): The Databricks workspace client.
        db_name (str): The name of the database in Lakebase.
        database_name (Optional[str], default="databricks_postgres"): The Lakebase database connection profile to use.

    Returns:
        sqlalchemy.engine.Engine: A SQLAlchemy engine connected to the specified Lakebase database.
    """
    database_url = get_postgres_connection(client, db_name, database_name)
    return create_engine(database_url)