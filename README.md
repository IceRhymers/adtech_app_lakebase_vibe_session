# Key-Value Configuration Editor with Databricks Lakebase

This project provides a simple Streamlit application for managing key-value pairs in a PostgreSQL database provisioned via Databricks Lakebase. The infrastructure is managed with Terraform, and the app is designed for secure, real-time configuration management.

---

## Quick Start

### 1. Deploy Infrastructure (Postgres via Databricks Lakebase)

All infrastructure is managed with Terraform. This will provision a PostgreSQL instance in Databricks Lakebase and set up access roles.

```bash
# Initialize Terraform
just terraform-init
# Review the plan
just terraform-plan
# Apply the infrastructure (creates the Postgres DB and access roles)
just terraform-apply
```

After applying, Terraform will output the connection string and group info. Save these for configuring the app.

---

### 2. Set Up and Run the App

The app is located in the `app/` directory. You can use the Justfile for common actions.

#### a. Create a Python Virtual Environment and Install Dependencies

```bash
cd app
just venv
```

#### b. Set Required Environment Variables

Set the Lakebase database name (from Terraform output):

```bash
export LAKEBASE_DB_NAME="vibe-session-db"
```

#### c. Run the App

```bash
just run
# or, manually:
streamlit run app.py
```

---

## Features
- Add, edit, and delete key-value pairs
- Real-time updates and duplicate key prevention
- Secure connection to Databricks Lakebase Postgres
- Role-based access via Databricks groups

---

## Dependencies
- Python 3.8+
- streamlit==1.38.0
- sqlalchemy==2.0.30
- alembic==1.13.1
- databricks-sdk==0.58.0
- psycopg2-binary==2.9.9
- debugpy==1.8.15

> **Note:** Some dependencies are pre-installed in Databricks Apps. See the [workspace rules](#) for version alignment.

---

## Database Schema
The app uses a simple table:

```sql
CREATE TABLE config_kv (
    id INTEGER PRIMARY KEY,
    key VARCHAR UNIQUE NOT NULL,
    value VARCHAR NOT NULL
);
```

---

## More Information
- For detailed app usage, see [`app/README.md`](app/README.md)
- For migration and database management, use the Justfile commands (e.g., `just migrations-generate`, `just migrations-upgrade`)
- For deployment, see the Justfile for `bundle-deploy`, `app-deploy`, and related commands

---

## Security & Best Practices
- Uses Databricks workspace authentication and secure SSL connections
- Input validation and duplicate key prevention
- Role-based access control via Databricks groups

---

## License
MIT 