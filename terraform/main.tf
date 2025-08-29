terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.84.0"
    }
  }
}

provider "databricks" {
  profile = var.databricks_cli_profile
}

variable "databricks_cli_profile" {
  type        = string
  description = "Databricks CLI profile to use"
  default     = "DEFAULT"
}

variable "database_instance_name" {
  type        = string
  description = "Name of the Databricks database instance"
  default     = "vibe-session-db"
}

variable "database_catalog_name" {
  type        = string
  description = "Name of the Databricks database catalog"
  default     = "vibe_session_postgres"
}

variable "database_group_name" {
  type        = string
  description = "Display name for the Databricks group with database access"
  default     = "Vibe Session DB Access Role"
}

# Secret management inputs
variable "secret_scope_name" {
  type        = string
  description = "Databricks secret scope to use or create if missing"
  default     = "field-eng"
}

variable "secret_name" {
  type        = string
  description = "Name (key) of the Databricks secret to create"
  default     = "app-secret"
}

variable "secret_value" {
  type        = string
  description = "Value of the Databricks secret to create; if empty, secret is not created"
  default     = "fake-token"
  sensitive   = true
}

resource "databricks_database_instance" "vibe_session_db" {
  name     = var.database_instance_name
  capacity = "CU_1"
  
  timeouts {
    create = "30m"
    update = "30m"
    delete = "30m"
  }
}

output "database_instance_name" {
  value       = databricks_database_instance.vibe_session_db.name
  description = "The name of the Databricks database instance."
}

output "postgres_connection_string" {
  value = "postgresql://<username>:<password>@${databricks_database_instance.vibe_session_db.read_write_dns}:5432/databricks_postgres?sslmode=require"
  description = "Connection string for the Databricks Postgres instance. Replace <username>, <password>, and <database> as needed."
}

resource "databricks_group" "postgres_role" {
  display_name = var.database_group_name
}

data "databricks_current_user" "me" {}

resource "databricks_group_member" "current_user_postgres_role" {
  group_id  = databricks_group.postgres_role.id
  member_id = data.databricks_current_user.me.id
}

resource "databricks_permissions" "app_usage" {
  database_instance_name = databricks_database_instance.vibe_session_db.name

  access_control {
    group_name       = databricks_group.postgres_role.display_name
    permission_level = "CAN_MANAGE"
  }

  depends_on = [databricks_group.postgres_role, databricks_database_instance.vibe_session_db]
}

output "postgres_role_group_id" {
  value       = databricks_group.postgres_role.id
  description = "The ID of the Databricks group used for Postgres DB access."
}

output "postgres_role_group_name" {
  value       = databricks_group.postgres_role.display_name
  description = "The display name of the Databricks group used for Postgres DB access."
}

# Create the secret scope if it doesn't exist
resource "databricks_secret_scope" "this" {
  name = var.secret_scope_name
}

# Create the secret in the provided scope
resource "databricks_secret" "this" {
  scope        = databricks_secret_scope.this.name
  key          = var.secret_name
  string_value = var.secret_value
}

output "secret_scope_used" {
  value       = var.secret_scope_name
  description = "Secret scope used (created if it did not exist)."
}

output "secret_name_created" {
  value       = var.secret_name
  description = "Secret name (key) created when a non-empty value is provided."
}

