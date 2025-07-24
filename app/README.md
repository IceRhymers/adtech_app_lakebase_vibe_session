# Key-Value Configuration Editor

A simple Streamlit application for managing key-value pairs in PostgreSQL using Databricks Lakebase.

## Features

- ✅ **Add** new key-value pairs
- ✏️ **Edit** existing values
- 🗑️ **Delete** key-value pairs
- 📋 **View** all current pairs in a clean table
- 🔄 **Real-time** updates
- 🛡️ **Duplicate key prevention**

## Setup

1. **Environment Variables**: Set the `LAKEBASE_DB_NAME` environment variable to your Lakebase database name:
   ```bash
   export LAKEBASE_DB_NAME="your-database-name"
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the App**:
   ```bash
   streamlit run app.py
   ```

## Usage

### Adding Key-Value Pairs
1. Use the form on the left side
2. Enter a unique key and value
3. Click "Save Pair"

### Editing Existing Pairs
1. Select a key from the dropdown on the right
2. Modify the value in the text input
3. Click "Update" to save changes

### Deleting Pairs
1. Select the key you want to delete
2. Click the "🗑️ Delete" button

## Database Schema

The app uses a simple `config_kv` table with the following structure:

```sql
CREATE TABLE config_kv (
    id INTEGER PRIMARY KEY,
    key VARCHAR UNIQUE NOT NULL,
    value VARCHAR NOT NULL
);
```

## Dependencies

- **streamlit==1.38.0** - Web app framework
- **databricks-sdk==0.33.0** - Databricks SDK for Lakebase connection
- **sqlalchemy==2.0.30** - Database ORM
- **psycopg2==2.9.9** - PostgreSQL adapter
- **alembic==1.13.1** - Database migrations

## Architecture

The app leverages:
- **Databricks Lakebase** for PostgreSQL database access
- **SQLAlchemy ORM** for database operations
- **Streamlit** for the web interface
- **Session management** for real-time updates

## Security

- Uses Databricks workspace authentication
- Secure database connections with SSL
- Input validation and duplicate key prevention
