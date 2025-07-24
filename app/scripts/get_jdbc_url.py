#!/usr/bin/env python3
"""
Script to generate JDBC URLs for Lakebase databases.
Reads configuration from alembic.ini file.
Usage: python get_jdbc_url.py [--profile PROFILE]
"""

import sys
import argparse
import configparser
from pathlib import Path

# Add the app directory to Python path so we can import lakebase
app_dir = Path(__file__).parent.parent
sys.path.insert(0, str(app_dir))

from databricks.sdk import WorkspaceClient
from lakebase import get_jdbc_url

def read_alembic_config():
    """Read database configuration from alembic.ini"""
    config = configparser.ConfigParser()
    alembic_ini_path = Path(__file__).parent.parent / 'alembic.ini'
    
    if not alembic_ini_path.exists():
        raise FileNotFoundError(f"alembic.ini not found at {alembic_ini_path}")
    
    config.read(alembic_ini_path)
    
    # Read from [databricks] section
    if 'databricks' not in config:
        raise ValueError("No [databricks] section found in alembic.ini")
    
    databricks_config = config['databricks']
    
    instance_name = databricks_config.get('instance_name')
    database_name = databricks_config.get('database_name', 'databricks_postgres')
    profile_name = databricks_config.get('profile_name')
    
    if not instance_name:
        raise ValueError("instance_name not found in [databricks] section of alembic.ini")
    
    return {
        'instance_name': instance_name,
        'database_name': database_name,
        'profile_name': profile_name
    }

def main():
    parser = argparse.ArgumentParser(description='Generate JDBC URL for Lakebase database using alembic.ini config')
    parser.add_argument('--profile', default=None,
                       help='Override Databricks profile to use (default: from alembic.ini or DEFAULT)')
    
    args = parser.parse_args()
    
    try:
        # Read configuration from alembic.ini
        config = read_alembic_config()
        
        # Use command line profile if provided, otherwise use config profile
        profile = args.profile or config['profile_name']
        
        # Create workspace client
        if profile:
            client = WorkspaceClient(profile=profile)
        else:
            client = WorkspaceClient()
        
        # Generate JDBC URL using config from alembic.ini
        jdbc_url = get_jdbc_url(client, config['instance_name'], config['database_name'])
        
        # Print the JDBC URL
        print(jdbc_url)
        
    except Exception as e:
        print(f"Error generating JDBC URL: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main() 