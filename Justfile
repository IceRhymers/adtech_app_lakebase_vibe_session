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

jdbc-url:
    cd app && .venv/bin/python scripts/get_jdbc_url.py

run: venv
    cd app && databricks apps run-local --prepare-environment --debug

clean:
    # Remove the .venv directory if it exists
    if [ -d "app/.venv" ]; then \
        rm -rf app/.venv; \
        echo 'Removed app/.venv'; \
    else \
        echo 'No virtual environment found at app/.venv'; \
    fi 