locals {
  required_services = toset([
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudtrace.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "cloudkms.googleapis.com",
    "logging.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "gmail.googleapis.com",
    "drive.googleapis.com",
    "docs.googleapis.com",
    "sheets.googleapis.com",
    "slides.googleapis.com",
    "calendar-json.googleapis.com",
    "chat.googleapis.com",
    "people.googleapis.com",
    "gmailmcp.googleapis.com",
    "drivemcp.googleapis.com",
    "docsmcp.googleapis.com",
    "sheetsmcp.googleapis.com",
    "slidesmcp.googleapis.com",
    "calendarmcp.googleapis.com",
    "chatmcp.googleapis.com",
  ])

  app_roles = toset([
    "roles/aiplatform.user",
    "roles/cloudtrace.agent",
    "roles/datastore.user",
    "roles/logging.logWriter",
    "roles/serviceusage.serviceUsageConsumer",
  ])
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "rally" {
  project       = var.project_id
  location      = var.region
  repository_id = "rally"
  description   = "Immutable Rally coordinator images"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "coordinator" {
  project      = var.project_id
  account_id   = "rally-coordinator"
  display_name = "Rally Google ADK coordinator"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "local_invoker" {
  project      = var.project_id
  account_id   = "rally-local-invoker"
  display_name = "Rally local bridge Cloud Run invoker"

  depends_on = [google_project_service.required]
}

resource "google_service_account" "control_plane" {
  project      = var.project_id
  account_id   = "rally-control-plane"
  display_name = "Rally customer identity and connection control plane"

  depends_on = [google_project_service.required]
}

resource "google_service_account_iam_member" "operator_token_creator" {
  service_account_id = google_service_account.local_invoker.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = var.operator_member
}

resource "google_project_iam_member" "coordinator" {
  for_each = local.app_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.coordinator.email}"
}

resource "google_project_iam_member" "control_plane" {
  for_each = toset([
    "roles/datastore.user",
    "roles/logging.logWriter",
  ])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.control_plane.email}"
}

resource "google_firestore_database" "rally" {
  project                     = var.project_id
  name                        = "(default)"
  location_id                 = "nam5"
  type                        = "FIRESTORE_NATIVE"
  concurrency_mode            = "PESSIMISTIC"
  app_engine_integration_mode = "DISABLED"
  delete_protection_state     = "DELETE_PROTECTION_ENABLED"
  deletion_policy             = "ABANDON"

  depends_on = [google_project_service.required]
}

resource "google_firestore_field" "auth_code_ttl" {
  project    = var.project_id
  database   = google_firestore_database.rally.name
  collection = "rally_auth_codes"
  field      = "expires_at"

  ttl_config {}
}

resource "google_firestore_field" "auth_session_ttl" {
  project    = var.project_id
  database   = google_firestore_database.rally.name
  collection = "rally_auth_sessions"
  field      = "expires_at"

  ttl_config {}
}

resource "google_firestore_field" "connector_oauth_flow_ttl" {
  project    = var.project_id
  database   = google_firestore_database.rally.name
  collection = "rally_connector_oauth_flows"
  field      = "expires_at"

  ttl_config {}
}

resource "google_firestore_field" "connector_execution_receipt_ttl" {
  project    = var.project_id
  database   = google_firestore_database.rally.name
  collection = "connector_execution_receipts"
  field      = "expires_at"

  ttl_config {}
}

resource "google_kms_key_ring" "connector_vault" {
  project  = var.project_id
  name     = "rally-connector-vault"
  location = var.region

  depends_on = [google_project_service.required]
}

resource "google_kms_crypto_key" "connector_credentials" {
  name            = "connector-credentials"
  key_ring        = google_kms_key_ring.connector_vault.id
  rotation_period = "7776000s"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key_iam_member" "control_plane" {
  crypto_key_id = google_kms_crypto_key.connector_credentials.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${google_service_account.control_plane.email}"
}

resource "random_password" "service_token" {
  length  = 48
  special = false
}

resource "google_secret_manager_secret" "service_token" {
  project   = var.project_id
  secret_id = "rally-cloud-service-token"

  lifecycle {
    prevent_destroy = true
  }

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "service_token" {
  secret      = google_secret_manager_secret.service_token.id
  secret_data = random_password.service_token.result
}

resource "google_secret_manager_secret_iam_member" "service_token_coordinator" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.service_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.coordinator.email}"
}

resource "google_secret_manager_secret" "workspace_oauth_client_secret" {
  project   = var.project_id
  secret_id = "rally-google-workspace-oauth-client-secret"

  lifecycle {
    prevent_destroy = true
  }

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "workspace_oauth_control_plane" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.workspace_oauth_client_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.control_plane.email}"
}

resource "google_cloud_run_v2_service" "coordinator" {
  count = var.deploy_service ? 1 : 0

  project             = var.project_id
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  labels = {
    product    = "rally"
    managed-by = "terraform"
  }

  template {
    service_account                  = google_service_account.coordinator.email
    timeout                          = "300s"
    max_instance_request_concurrency = 8

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.image_uri

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "True"
      }
      env {
        name  = "GEMINI_MODEL"
        value = "gemini-3.7-flash"
      }
      env {
        name  = "RALLY_STATE_BACKEND"
        value = "firestore"
      }
      env {
        name  = "RALLY_A2A_BASE_URL"
        value = var.a2a_base_url
      }
      env {
        name  = "RALLY_ENABLE_CLOUD_TRACE"
        value = "1"
      }
      env {
        name  = "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"
        value = "false"
      }
      env {
        name  = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
        value = "NO_CONTENT"
      }
      env {
        name = "RALLY_SERVICE_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.service_token.secret_id
            version = "latest"
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 5
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_firestore_database.rally,
    google_project_iam_member.coordinator,
    google_secret_manager_secret_version.service_token,
    google_secret_manager_secret_iam_member.service_token_coordinator,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "invoker" {
  count = var.deploy_service ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.coordinator[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.local_invoker.email}"
}

resource "google_cloud_run_v2_service" "control_plane" {
  count = var.deploy_control_plane ? 1 : 0

  lifecycle {
    precondition {
      condition     = var.google_web_client_id != ""
      error_message = "google_web_client_id is required before deploying the control plane."
    }
  }

  project             = var.project_id
  name                = var.control_plane_service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  labels = {
    product    = "rally"
    surface    = "customer-control-plane"
    managed-by = "terraform"
  }

  template {
    service_account                  = google_service_account.control_plane.email
    timeout                          = "60s"
    max_instance_request_concurrency = 40

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = (
        var.control_plane_image_uri != ""
        ? var.control_plane_image_uri
        : var.image_uri
      )
      command = ["uv"]
      args = [
        "run",
        "--no-sync",
        "uvicorn",
        "control_plane:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8080",
      ]

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "RALLY_VAULT_BACKEND"
        value = "google_kms"
      }
      env {
        name  = "RALLY_KMS_KEY"
        value = google_kms_crypto_key.connector_credentials.id
      }
      env {
        name  = "RALLY_GOOGLE_WEB_CLIENT_IDS"
        value = var.google_web_client_id
      }
      dynamic "env" {
        for_each = var.google_workspace_client_id == "" ? [] : [var.google_workspace_client_id]
        content {
          name  = "RALLY_GOOGLE_WORKSPACE_CLIENT_ID"
          value = env.value
        }
      }
      dynamic "env" {
        for_each = var.google_workspace_client_id == "" ? [] : [1]
        content {
          name = "RALLY_GOOGLE_WORKSPACE_CLIENT_SECRET"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.workspace_oauth_client_secret.secret_id
              version = "latest"
            }
          }
        }
      }
      env {
        name  = "RALLY_ALLOWED_ORIGINS"
        value = join(",", var.control_plane_allowed_origins)
      }
      env {
        name  = "RALLY_ALLOWED_USER_EMAILS"
        value = join(",", var.control_plane_allowed_user_emails)
      }
      env {
        name  = "RALLY_WORKSPACE_ID"
        value = var.workspace_id
      }
      env {
        name  = "RALLY_AUTH_BACKEND"
        value = "firestore"
      }
      env {
        name  = "RALLY_OAUTH_BACKEND"
        value = "firestore"
      }
      env {
        name  = "RALLY_ADMIN_RETURN_URL"
        value = "https://rally.agent9.dev/admin/"
      }

      startup_probe {
        initial_delay_seconds = 2
        timeout_seconds       = 3
        period_seconds        = 5
        failure_threshold     = 12
        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_firestore_database.rally,
    google_firestore_field.auth_code_ttl,
    google_firestore_field.auth_session_ttl,
    google_firestore_field.connector_oauth_flow_ttl,
    google_firestore_field.connector_execution_receipt_ttl,
    google_kms_crypto_key_iam_member.control_plane,
    google_secret_manager_secret_iam_member.workspace_oauth_control_plane,
    google_project_iam_member.control_plane,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "control_plane_public" {
  count = var.deploy_control_plane ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.control_plane[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
