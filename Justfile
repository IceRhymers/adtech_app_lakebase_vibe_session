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

# Initialize Terraform working directory
terraform-init:
    cd terraform && terraform init

# Create and preview infrastructure changes
terraform-plan:
    cd terraform && terraform plan -out plan.tfplan

# Apply infrastructure changes
terraform-apply:    
    cd terraform && terraform apply plan.tfplan

# Destroy all managed infrastructure
terraform-destroy:
    cd terraform && terraform destroy

# Create the with terraform
create-database: terraform-init terraform-plan terraform-apply
    echo "Database created"

# Generate a new migration file
migrations-generate MESSAGE:
    cd app && .venv/bin/alembic revision --autogenerate -m "{{MESSAGE}}"

# Upgrade the database to the latest version
migrations-upgrade:
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
full-deploy: create-database bundle-deploy migrations-upgrade app-permissions app-start app-deploy
    echo "Full deploy complete"

clean:
    # Remove the .venv directory if it exists
    if [ -d "app/.venv" ]; then \
        rm -rf app/.venv; \
        echo 'Removed app/.venv'; \
    else \
        echo 'No virtual environment found at app/.venv'; \
    fi 