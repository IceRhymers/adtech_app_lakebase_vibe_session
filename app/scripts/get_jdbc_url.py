#!/usr/bin/env python3
"""
Script to generate JDBC URLs for Lakebase databases.
Reads configuration from alembic.ini file.
Usage: python get_jdbc_url.py [--profile PROFILE]
"""

import sys
import argparse
import configparser
import logging
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
    parser.add_argument('--instance-name', default=None,
                       help='Override database instance name (default: from alembic.ini)')
    parser.add_argument('--database-name', default=None,
                       help='Override database name (default: from alembic.ini or databricks_postgres)')
    parser.add_argument('--debug', action='store_true',
                       help='Enable debug logging')
    
    args = parser.parse_args()
    
    # Configure logging to stderr
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s', stream=sys.stderr)
    else:
        logging.basicConfig(level=logging.WARNING, format='%(levelname)s: %(message)s', stream=sys.stderr)
    
    logger = logging.getLogger(__name__)
    
    # Always show what arguments we received for debugging
    print(f"DEBUG: Starting JDBC URL generation with args: {args}", file=sys.stderr)
    print(f"DEBUG: Raw sys.argv: {sys.argv}", file=sys.stderr)
    
    try:
        # Read configuration from alembic.ini
        config = read_alembic_config()
        logger.debug(f"Config from alembic.ini: {config}")
        
        # Use command line arguments if provided, otherwise use config values
        profile = args.profile if args.profile is not None else config['profile_name']
        instance_name = args.instance_name if args.instance_name is not None else config['instance_name']
        database_name = args.database_name if args.database_name is not None else config['database_name']
        
        logger.debug(f"Using profile: {profile}")
        logger.debug(f"Using instance_name: {instance_name}")
        logger.debug(f"Using database_name: {database_name}")
        
        # Create workspace client
        if profile:
            client = WorkspaceClient(profile=profile)
        else:
            client = WorkspaceClient()
        
        logger.debug(f"Created workspace client with profile: {profile}")
        logger.debug(f"Attempting to get database instance: {instance_name}")
        
        # Generate JDBC URL using provided or config values
        jdbc_url = get_jdbc_url(client, instance_name, database_name)
        
        # Print the JDBC URL
        print(jdbc_url)
        
    except Exception as e:
        import traceback
        print(f"Error generating JDBC URL: {e}", file=sys.stderr)
        print("\nFull traceback:", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main() 