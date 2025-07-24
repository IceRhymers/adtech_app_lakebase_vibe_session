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

migrations-generate MESSAGE:
    cd app && .venv/bin/alembic revision --autogenerate -m "{{MESSAGE}}"

migrations-upgrade:
    cd app && .venv/bin/alembic upgrade head

# Generate a JDBC URL for use in a SQL Workbench, using the same configuration as Alembic.
# This target runs a script that outputs the JDBC connection string based on your alembic.ini settings.
jdbc-url:
    cd app && .venv/bin/python scripts/get_jdbc_url.py

run: venv
    cd app && databricks apps run-local --prepare-environment --debug

bundle-deploy: 
    databricks bundle deploy

app-start: 
    APP_NAME=$(databricks bundle summary -o json | jq -r '.resources.apps | to_entries | first | .value.name') && \
    COMPUTE_STATUS=$(databricks apps get $APP_NAME | jq -r '.compute_status.state') && \
    if [ "$COMPUTE_STATUS" = "ACTIVE" ]; then \
        echo "App $APP_NAME is already running"; \
    else \
        databricks apps start "$APP_NAME"; \
    fi

app-stop:
    APP_NAME=$(databricks bundle summary -o json | jq -r '.resources.apps | to_entries | first | .value.name') && \
    databricks apps stop "$APP_NAME"

app-deploy:
    APP_NAME=$(databricks bundle summary -o json | jq -r '.resources.apps | to_entries | first | .value.name') && \
    WORKSPACE_PATH=$(databricks bundle summary -o json | jq -r '.workspace.file_path') && \
    echo "Deploying app: $APP_NAME" && \
    databricks apps deploy "$APP_NAME" --source-code-path "$WORKSPACE_PATH/app"

full-deploy: bundle-deploy app-deploy app-start
    echo "Full deploy complete"

clean:
    # Remove the .venv directory if it exists
    if [ -d "app/.venv" ]; then \
        rm -rf app/.venv; \
        echo 'Removed app/.venv'; \
    else \
        echo 'No virtual environment found at app/.venv'; \
    fi 