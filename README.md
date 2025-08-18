# AI Chatbot with Databricks Lakebase and Vector Search

This project provides a sophisticated AI chatbot application built with Dash that leverages Databricks Lakebase for data persistence and includes vector search capabilities for intelligent conversation handling. The infrastructure is managed with Terraform, and the app includes a notebook to deploy the AI agent.

---

### Required Tools

- **[Databricks CLI](https://docs.databricks.com/en/dev-tools/cli/index.html)** - Command-line interface for Databricks workspace management and app deployment
- **[Terraform](https://developer.hashicorp.com/terraform/tutorials/aws-get-started/install-cli)** - Infrastructure as Code tool for provisioning Databricks Lakebase resources
- **[jq](https://stedolan.github.io/jq/download/)** - Lightweight command-line JSON processor used in deployment scripts
- **[just](https://github.com/casey/just#installation)** - Command runner for executing project tasks and workflows
- **[uv](https://github.com/astral-sh/uv)** - Fast Python package installer and resolver

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
pip install uv
```

#### Manual Installation
- **Databricks CLI**: Follow the [official installation guide](https://docs.databricks.com/en/dev-tools/cli/install.html)
- **Terraform**: Download from [terraform.io](https://developer.hashicorp.com/terraform/downloads)
- **jq**: Available on most package managers or download from [jqlang.github.io/jq](https://jqlang.github.io/jq/download/)
- **just**: Install via [cargo](https://crates.io/crates/just) or download from [GitHub releases](https://github.com/casey/just/releases)
- **uv**: Install with `pip install uv` or follow [installation guide](https://github.com/astral-sh/uv)

### Verification
After installation, verify all tools are working:

```bash
databricks --version
terraform --version
jq --version
just --version
uv --version
```

## Quick Start

### 0. Full End-to-End Deployment

If you want to get straight into the experience, this project can build and deploy end to end with `just full-deploy` using your default Databricks CLI profile. But more careful instructions are below.

### 1. Clone Repository and Configure Bundle

```bash
git clone <this-repository-url>
cd adtech_app_lakebase_vibe_session
```

Edit the `databricks.yml` to point to your workspace:

```yaml
targets:
  dev:
    mode: development
    default: true
    workspace:
      host: https://YOUR_WORKSPACE_HERE.cloud.databricks.com
```

### 2. Deploy Infrastructure (PostgreSQL via Databricks Lakebase)

All infrastructure is managed with Terraform. This will provision a PostgreSQL instance in Databricks Lakebase and set up a group for access roles:

```bash
# Initialize and deploy terraform in one command
just terraform-full
```

Or step by step:

```bash
# Generate terraform variables (optional customization)
just terraform-init-vars
# Initialize Terraform
just terraform-init
# Review the plan
just terraform-plan
# Apply the infrastructure
just terraform-apply
```

After applying, Terraform will output the connection string and group info.

---

### 3. Set Up the Application

#### a. Create Python Virtual Environment and Install Dependencies

```bash
just venv
```

#### b. Configure Environment Variables

The app uses `app/app.yml` to configure environment variables. The default configuration includes:

```yaml
env:
  - name: "LAKEBASE_DB_NAME"
    value: "tannerw-adtech-db"
  - name: "POSTGRES_GROUP"
    value: "Tanner W Adtech DB Access Role"
  - name: "AGENT_ENDPOINT"
    value: "tanner_wendland-default-chat_history_agent"
```

| Variable Name      | Description                                                | Example Value                           | Required |
|--------------------|------------------------------------------------------------|-----------------------------------------|----------|
| `LAKEBASE_DB_NAME` | Name of the Databricks Lakebase Postgres database instance | `tannerw-adtech-db`                     | Yes      |
| `POSTGRES_GROUP`   | Name of the Databricks group with access to the database   | `Tanner W Adtech DB Access Role`        | No       |
| `AGENT_ENDPOINT`   | Name of the serving endpoint for the AI agent             | `tanner_wendland-default-chat_history_agent` | Yes       |

Update these values in `app/app.yml` to match your environment.

#### c. Configure Alembic.ini

If you changed the database instance name in terraform, configure `app/alembic.ini` to match your database instance name.

#### d. Run Database Migrations

Apply database migrations to set up the chat history tables:

```bash
just migrations-upgrade
```

This creates the necessary tables for chat sessions and message history.

#### e. Run the Application

For local development, you may need to configure the Databricks SDK:

```bash
export DATABRICKS_CONFIG_PROFILE=DEFAULT
```

Then run the app:

```bash
just run
```

---

## Features

### Chatbot Application
- 🤖 **AI-powered conversations** with persistent history
- 💾 **Full conversation history** saved to PostgreSQL database
- 🧵 **Multiple chat sessions** with easy switching
- 👤 **User identification** via Databricks authentication
- 🔄 **Real-time chat interface** with Streamlit

### Data Pipelines
- 📊 **Chat History Sync** - Syncs chat data for analysis
- 🔍 **Vector Search Integration** - Enables semantic search over conversations
- 🤖 **AI Agent Jobs** - Automated processing of chat history
- ⏰ **Scheduled Jobs** - Automated data pipeline execution

### Infrastructure
- 🏗️ **Terraform-managed infrastructure** - PostgreSQL via Databricks Lakebase
- 🔐 **Role-based access control** via Databricks groups
- 🚀 **Databricks Apps deployment** with automated permissions

---

## Architecture

```
┌─────────────────────────┐      ┌──────────────────────────────────────┐
│         Dash App        │◄────►│ Lakebase (PostgreSQL + pgvector)     │
│  (computes embeddings)  │      │   - app state + vector store         │
└──────────┬──────────────┘      └──────────────────────────────────────┘
           │                              ▲
           │                              │
           ▼                              │
┌─────────────────────────┐               │
│       AI Agent          │◄──────────────┘
│       Endpoint          │
└───────────▲─────────────┘
            │
┌───────────┴─────────────┐
│ Notebooks (deploy agent)│
└─────────────────────────┘
```

**Component Interactions:**
- **Dash App** ↔ **Lakebase (PostgreSQL + pgvector)**: Stores app state (sessions, messages) and embeddings; computes embeddings in-app and upserts to the pgvector index
- **Dash App** ↔ **AI Agent Endpoint**: Sends user messages and receives AI responses; both query Lakebase pgvector for context
- **AI Agent Endpoint** ↔ **Lakebase**: Reads/writes as needed and performs vector search over embeddings stored in Lakebase
- **Notebooks** → **AI Agent Endpoint**: Used to deploy/update the agent endpoint; not required for app runtime

## Dependencies

- Python 3.10+
- streamlit==1.38.0
- sqlalchemy==2.0.30
- alembic==1.13.1
- databricks-sdk==0.58.0
- psycopg2-binary==2.9.9
- debugpy==1.8.15

> **Note:** Some dependencies are pre-installed in Databricks Apps. See the workspace rules for version alignment.

---

## Database Schema

The application uses the following main tables:

```sql
-- Chat sessions
CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY,
    user_name VARCHAR NOT NULL,
    session_title VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Chat history/messages
CREATE TABLE chat_history (
    id UUID PRIMARY KEY,
    chat_session_id UUID REFERENCES chat_sessions(id),
    message_type VARCHAR NOT NULL,  -- 'USER' or 'ASSISTANT'
    message_content TEXT NOT NULL,
    message_order INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## Data Pipelines

The project includes several data pipeline notebooks in `data_pipelines/src/`:

1. **`00-postgres-catalog.ipynb`** - Sets up catalog connection to PostgreSQL
2. **`01-sync-chat-history.ipynb`** - Syncs chat history for vector search
3. **`02-chat-history-agent.ipynb`** - Creates AI agent for chat analysis

These are orchestrated via Databricks Jobs defined in `resources/adtech_vector_chat.job.yml`.

---

## Available Commands

### Environment Setup
- `just venv` - Create virtual environment and install dependencies
- `just clean` - Remove virtual environment and cache files

### Infrastructure
- `just terraform-init` - Initialize terraform
- `just terraform-plan` - Plan terraform changes
- `just terraform-apply` - Apply terraform changes
- `just terraform-full` - Deploy terraform end-to-end
- `just terraform-destroy` - Destroy terraform infrastructure

### Database Management
- `just migrations-generate "message"` - Generate new migration
- `just migrations-upgrade` - Apply pending migrations
- `just jdbc-url` - Get JDBC connection string
- `just wait-for-database` - Wait for database to be available

### Development
- `just run` - Run application locally

### Deployment
- `just bundle-deploy` - Deploy Databricks bundle
- `just app-start` - Start app compute
- `just app-stop` - Stop app compute
- `just app-deploy` - Deploy app to running compute
- `just app-permissions` - Configure app permissions
- `just agent-deploy` - Deploy data pipeline agent
- `just full-deploy` - Complete end-to-end deployment

---

## Security & Best Practices

- Uses Databricks workspace authentication and secure SSL connections
- Role-based access control via Databricks groups
- Automatic service principal management for app permissions
- Input validation and SQL injection prevention
- Secure handling of chat history and user data

---

## More Information

- For detailed app usage, see [`app/README.md`](app/README.md)
- For data pipeline details, explore the notebooks in `data_pipelines/src/`
- Use `just --list` to see all available commands with descriptions

---

## License

MIT 