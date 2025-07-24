# Databricks App Accelerator

## Purpose

This repository provides a customer-facing template to accelerate the development and deployment of Databricks Apps. It is designed to help customers build, customize, and deploy Python-based applications on Databricks, leveraging Lakebase (managed Postgres) for state management. The `app` directory is intended to be deployed to a Databricks workspace using a Databricks Asset Bundle (DAB), enabling rapid prototyping and productionization of data and AI use-cases.

## Key Features

- **Lakebase Integration:** Uses managed Postgres (Lakebase) for robust, scalable state management.
- **Framework Flexibility:** Supports leading Python app frameworks: Dash, Gradio, Shiny, and Streamlit.
- **CI/CD Ready:** Designed for integration with GitHub Actions and Databricks Asset Bundles for automated deployments.
- **Local Development:** Easily run and test your app locally before deploying to Databricks.
- **Secure and Compliant:** Follows Databricks best practices for security, logging, and resource management.

## Best Practices for Databricks Apps

### 1. Requirements Management
- Use a `requirements.txt` file with **pinned package versions** to ensure reproducible environments.
  - Example:
    ```
    streamlit==1.35.0
    pandas==2.2.2
    ```
- Install dependencies locally with:
    ```
    pip install -r requirements.txt
    ```

### 2. Supported Frameworks
- The following Python frameworks are recommended and best supported for Databricks Apps:
  - [Dash](https://plotly.com/dash/)
  - [Gradio](https://www.gradio.app/)
  - [Shiny](https://shiny.posit.co/py/)
  - [Streamlit](https://streamlit.io/)
- Choose the framework that best fits your use-case and user experience needs.

### 3. App Structure
- Place all app source code and configuration files in the `app` directory.
- The main entry point should be named `app.py` (or as specified in your `app.yaml`).
- Include an `app.yaml` file to define app configuration, entry point, and permissions.
- App files must not exceed 10 MB each ([see limits](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/tutorial-streamlit.html#limitations)).

### 4. Local Development & Testing
- Develop and test your app locally using the same dependencies as in production.
- Run your app locally with:
    ```
    python app.py
    ```
- For frameworks like Streamlit or Gradio, use their respective CLI commands:
    ```
    streamlit run app.py
    gradio app.py
    ```
- Optionally, use the Databricks CLI for local debugging:
    ```
    databricks apps run-local --prepare-environment --debug
    ```

### 5. Deployment via Databricks Asset Bundles
- Use Databricks Asset Bundles (DABs) to package and deploy your app to the Databricks workspace.
- Follow the [Databricks Asset Bundles documentation](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/get-started.html) for setup and deployment steps.
- Automate deployments with CI/CD tools like GitHub Actions for production-grade workflows.

### 6. Security, Logging, and Platform Best Practices
- **Use Databricks-native features for data processing**: Use Databricks SQL, Lakeflow Jobs, and Model Serving for heavy workloads; keep app compute focused on UI rendering.
- **Follow secure coding practices**: Parameterize SQL queries, validate and sanitize all user input, and handle errors gracefully.
- **Graceful shutdown**: Your app must shut down within 15 seconds after receiving a `SIGTERM` signal.
- **Avoid privileged operations**: Apps run as non-privileged users; do not require root access.
- **Networking**: Bind your app to `0.0.0.0` and use the port specified in the `DATABRICKS_APP_PORT` environment variable.
- **Minimize startup time**: Keep initialization lightweight; avoid blocking operations during startup.
- **Logging**: Log to stdout and stderr; avoid writing logs to local files.
- **Error handling**: Implement global exception handling and avoid exposing stack traces or sensitive data.
- **In-memory caching**: Use in-memory caching for expensive operations, but scope caches carefully in multi-user apps.
- **App permissions**: Manage app permissions and access control via `app.yaml` and Databricks workspace settings. Apps are only accessible to authenticated Databricks users.
- **File size limits**: No single file in the app directory may exceed 10 MB.

### 7. Version Control & Collaboration
- Use Git for source control and collaboration.
- Protect main branches and use pull requests for code reviews and automated testing.
- Tag releases to trigger production deployments via CI/CD.

### 8. Monitoring & Maintenance
- Monitor app health and deployment status via the Databricks workspace UI.
- Set up alerts and logging for production apps.
- Regularly update dependencies and rotate credentials.

## Getting Started

1. **Clone this repository and navigate to the `app` directory.**
2. **Install dependencies:**
    ```
    pip install -r requirements.txt
    ```
3. **Develop and test your app locally.**
4. **Deploy to Databricks using Databricks Asset Bundles.**
5. **Monitor and iterate on your app in the Databricks workspace.**

## References & Further Reading

- [Databricks Apps: Best Practices](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/best-practices.html)
- [Databricks Apps: Key Concepts](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/key-concepts.html)
- [Databricks Apps: Streamlit Tutorial](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/tutorial-streamlit.html)
- [Automate Databricks Apps Deployments with GitHub Actions and DABs](https://apps-cookbook.dev/blog/automate-apps-deployments-dabs/)

---

For more information, see the [Databricks Apps documentation](https://docs.databricks.com/aws/en/dev-tools/databricks-apps/get-started.html).
