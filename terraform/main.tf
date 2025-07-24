terraform {
  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = ">= 1.84.0"
    }
  }
}

provider "databricks" {
  profile = "DEFAULT"
}

variable "manage_principals" {
  type  = list(string)
  default = []
}

resource "databricks_database_instance" "vibe_session_db" {
  name     = "vibe-session-db"
  capacity = "CU_1"
}

output "postgres_connection_string" {
  value = "postgresql://<username>:<password>@${databricks_database_instance.vibe_session_db.read_write_dns}:5432/databricks_postgres?sslmode=require"
  description = "Connection string for the Databricks Postgres instance. Replace <username>, <password>, and <database> as needed."
}

resource "databricks_group" "postgres_role" {
  display_name = "Vibe Session DB Access Role"
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