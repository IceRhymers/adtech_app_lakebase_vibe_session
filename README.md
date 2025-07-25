# Key-Value Configuration Editor with Databricks Lakebase

This project provides a simple Streamlit application for managing key-value pairs in a PostgreSQL database provisioned via Databricks Lakebase. The infrastructure is managed with Terraform, and the app is designed for secure, real-time configuration management.

---


### Required Tools

- **[Databricks CLI](https://docs.databricks.com/en/dev-tools/cli/index.html)** - Command-line interface for Databricks workspace management and app deployment
- **[Terraform](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)** - Infrastructure as Code tool for provisioning Databricks Lakebase resources
- **[jq](https://stedolan.github.io/jq/download/)** - Lightweight command-line JSON processor used in deployment scripts
- **[just](https://github.com/casey/just#installation)** - Command runner for executing project tasks and workflows

### Installation Options

#### macOS (Recommended)
If you are on macOS, you can install all tools using [Homebrew](https://brew.sh/):

```bash
# Install Homebrew if you haven't already
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install all required tools
brew install databricks/tap/databricks
brew install terraform
brew install jq
brew install just
```

#### Manual Installation
- **Databricks CLI**: Follow the [official installation guide](https://docs.databricks.com/en/dev-tools/cli/install.html)
- **Terraform**: Download from [terraform.io](https://developer.hashicorp.com/terraform/downloads)
- **jq**: Available on most package managers or download from [jqlang.github.io/jq](https://jqlang.github.io/jq/download/)
- **just**: Install via [cargo](https://crates.io/crates/just) or download from [GitHub releases](https://github.com/casey/just/releases)

### Verification
After installation, verify all tools are working:

```bash
databricks --version
terraform --version
jq --version
just --version
```

## Quick Start

### 0. Full send deployment, no edit.

If you want to just get straight into the vibe, this project can build and deploy end to end with `just full-deploy` using your default Databricks CLI profile. But more careful instructions are below.

### 1. Clone repo and edit bundle.

```bash
git clone <<this repo whenever I make it>
```

Then you need to edit the `databricks.yml` to point to your workspace

```yaml
targets:
  dev:
    mode: development
    default: true
    workspace:
      host: https://YOUR_WORKSPACE_HERE.cloud.databricks.com
```

### 2. Deploy Infrastructure (Postgres via Databricks Lakebase)

All infrastructure is managed with Terraform. This will provision a PostgreSQL instance in Databricks Lakebase and set up a group that will be used for access roles. This will use your default CLI profile and can be changed in `main.tf` if required. You can easily run the terraform with 

```bash
# Optionally generate terraform inputs for instance and group name overrides
just terraform-init-vars
# Initialize Terraform
just terraform-init
# Review the plan
just terraform-plan
# Apply the infrastructure (creates the Postgres DB and workspace group)
just terraform-apply
```

Or just simply

`just terraform-full`

After applying, Terraform will output the connection string and group info. Save these for configuring the app.

---

### 3. Set Up the App

The app is located in the `app/` directory. You can use the Justfile for common actions. 

#### a. Create a Python Virtual Environment and Install Dependencies

```bash
just venv
```

#### b. Configure Environment Variables

The app uses `app/app.yml` to configure environment variables for Databricks Apps, and will work when using `just run` to run locally. The configuration includes:

```yaml
env:
  - name: "LAKEBASE_DB_NAME"
    value: "vibe-session-db"
  - name: "POSTGRES_GROUP"
    value: "Vibe Session DB Access Role"
```

| Variable Name      | Description                                                | Example Value                    | Required |
|--------------------|------------------------------------------------------------|----------------------------------|----------|
| `LAKEBASE_DB_NAME` | Name of the Databricks Lakebase Postgres database instance | `vibe-session-db`                | Yes      |
| `POSTGRES_GROUP`   | Name of the Databricks group with access to the database   | `Vibe Session DB Access Role`    | No      |


If you need to override these values for different environments, you can modify the `app.yml` file or use the `valueFrom` field to reference external sources like secrets. 

#### c. Configure `alemblic.ini`

If you changed the name of the database instance in terraform, you'll need to configure `alembic.ini` to look for your database instance. The default values align to what terraform deploys out of the box.

#### d. Run Database Migrations

Before running the app, you need to apply the database migrations to set up the PostgreSQL role and permissions:

```bash
just migrations-upgrade
```

This migration creates the PostgreSQL role for the Databricks group and grants the necessary permissions (SELECT, INSERT, UPDATE, DELETE) on the database tables.

#### e. Run the App

You may need to configure the Databricks SDK with environment variables to run locally, since the default credential chain doesn't work. 

```bash
export DATABRICKS_CONFIG_PROFILE=DEFAULT
```

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
- Python 3.10+
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