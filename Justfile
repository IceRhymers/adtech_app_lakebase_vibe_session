# Create a virtual environment for the app
venv:
    # Check if 'uv' is installed
    if ! command -v uv >/dev/null 2>&1; then \
        echo 'Error: uv is not installed. Install it with `pip install uv` or see https://github.com/astral-sh/uv'; \
        exit 1; \
    fi
    # Create .venv if it does not exist
    if [ ! -d "app/.venv" ]; then \
        uv venv app/.venv; \
    fi
    # Install requirements
    uv pip install -r app/requirements.txt --python app/.venv/bin/python

# Initialize terraform for lakebase deployment
terraform-init:
    cd terraform && terraform init

# Create terraform.tfvars file to override default values
terraform-init-vars:
    cd terraform && if [ ! -f terraform.tfvars ]; then \
        echo "database_instance_name = \"vibe-session-db\"" > terraform.tfvars; \
        echo "database_group_name = \"Vibe Session DB Access Role\"" >> terraform.tfvars; \
        echo "Created terraform.tfvars file"; \
    else \
        echo "terraform.tfvars already exists, skipping creation"; \
    fi

# Plann terraform changes for lakebase deployment
terraform-plan: terraform-init-vars
    cd terraform && terraform plan -out plan.tfplan -var-file=terraform.tfvars

# Apply terraform changes for lakebase deployment
terraform-apply:
    cd terraform && terraform apply plan.tfplan

# Full terraform deployment for lakebase deployment.
terraform-full: terraform-init-vars terraform-init terraform-plan terraform-apply
    echo "Terraform deployment complete"

# Destroy terraform managed infrastructure
terraform-destroy:
    cd terraform && terraform destroy

# Wait for database instance to be available
wait-for-database:
    DATABASE_NAME=$(cd terraform && terraform output -raw database_instance_name) && \
    echo "Checking database instance: $DATABASE_NAME" && \
    while true; do \
        STATE=$(databricks database get-database-instance "$DATABASE_NAME" | jq -r '.state') && \
        echo "Database state: $STATE" && \
        if [ "$STATE" = "AVAILABLE" ]; then \
            echo "Database is available!" && \
            break; \
        elif [ "$STATE" = "STARTING" ]; then \
            echo "Database is starting, waiting 30 seconds..." && \
            sleep 30; \
        else \
            echo "ERROR: Database is in unexpected state: $STATE" && \
            echo "Manual intervention may be required. Expected states: STARTING, AVAILABLE" && \
            exit 1; \
        fi; \
    done

# Generate a new migration file
migrations-generate MESSAGE: wait-for-database
    cd app && .venv/bin/alembic revision --autogenerate -m "{{MESSAGE}}"

# Upgrade the database to the latest version
migrations-upgrade: wait-for-database
    cd app && .venv/bin/alembic upgrade head

# Generate a JDBC URL for use in a SQL Workbench, using the same configuration as Alembic.
jdbc-url:
    cd app && .venv/bin/python scripts/get_jdbc_url.py

# Run the app locally
run: venv
    cd app && databricks apps run-local --prepare-environment --debug

# Deploy the bundle to Databricks
bundle-deploy: 
    databricks bundle deploy

# Start the app compute (if not already running)
app-start: 
    APP_NAME=$(databricks bundle summary -o json | jq -r '.resources.apps | to_entries | first | .value.name') && \
    COMPUTE_STATUS=$(databricks apps get $APP_NAME | jq -r '.compute_status.state') && \
    if [ "$COMPUTE_STATUS" = "ACTIVE" ]; then \
        echo "App $APP_NAME is already running"; \
    else \
        databricks apps start "$APP_NAME"; \
    fi

# Stop the app compute
app-stop:
    APP_NAME=$(databricks bundle summary -o json | jq -r '.resources.apps | to_entries | first | .value.name') && \
    databricks apps stop "$APP_NAME"

# Give the app compute access to the database
app-permissions: bundle-deploy
    APP_NAME=$(databricks bundle summary -o json | jq -r '.resources.apps | to_entries | first | .value.name') && \
    SERVICE_PRINCIPAL_ID=$(databricks apps get $APP_NAME | jq -r '.service_principal_id') && \
    DATABASE_GROUP_ID=$(cd terraform && terraform output -raw postgres_role_group_id) && \
    echo "Setting permissions for app $APP_NAME" && \
    echo "Assigning service principal $SERVICE_PRINCIPAL_ID to group $DATABASE_GROUP_ID" && \
    echo "{\"schemas\":[\"urn:ietf:params:scim:api:messages:2.0:PatchOp\"],\"Operations\":[{\"op\":\"add\",\"path\":\"members\",\"value\":[{\"value\":\"$SERVICE_PRINCIPAL_ID\"}]}]}" && \
    if ! databricks groups get $DATABASE_GROUP_ID | jq -e ".members // [] | .[] | select(.value == \"$SERVICE_PRINCIPAL_ID\")" > /dev/null; then \
        echo "Adding service principal $SERVICE_PRINCIPAL_ID to group $DATABASE_GROUP_ID" && \
        databricks groups patch $DATABASE_GROUP_ID --json "{\"schemas\":[\"urn:ietf:params:scim:api:messages:2.0:PatchOp\"],\"Operations\":[{\"op\":\"add\",\"path\":\"members\",\"value\":[{\"value\":\"$SERVICE_PRINCIPAL_ID\"}]}]}"; \
    else \
        echo "Service principal $SERVICE_PRINCIPAL_ID is already a member of group $DATABASE_GROUP_ID"; \
    fi

# Deploy the app to Databricks
app-deploy:
    APP_NAME=$(databricks bundle summary -o json | jq -r '.resources.apps | to_entries | first | .value.name') && \
    WORKSPACE_PATH=$(databricks bundle summary -o json | jq -r '.workspace.file_path') && \
    echo "Deploying app: $APP_NAME" && \
    databricks apps deploy "$APP_NAME" --source-code-path "$WORKSPACE_PATH/app"

# Full end to end deployment.
full-deploy: terraform-full bundle-deploy migrations-upgrade app-permissions app-start app-deploy
    echo "Full deploy complete"

# Clean up the virtual environment
clean:
    # Remove the .venv directory if it exists
    if [ -d "app/.venv" ]; then \
        rm -rf app/.venv; \
        echo 'Removed app/.venv'; \
    else \
        echo 'No virtual environment found at app/.venv'; \
    fi
    # Remove all __pycache__ directories
    find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    echo 'Removed all __pycache__ directories' 