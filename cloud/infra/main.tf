locals {
  required_services = toset([
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudtrace.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "logging.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
  ])

  app_roles = toset([
    "roles/aiplatform.user",
    "roles/cloudtrace.agent",
    "roles/datastore.user",
    "roles/logging.logWriter",
    "roles/secretmanager.secretAccessor",
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

resource "google_project_iam_member" "coordinator" {
  for_each = local.app_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.coordinator.email}"
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

resource "random_password" "service_token" {
  length  = 48
  special = false
}

resource "google_secret_manager_secret" "service_token" {
  project   = var.project_id
  secret_id = "rally-cloud-service-token"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "service_token" {
  secret      = google_secret_manager_secret.service_token.id
  secret_data = random_password.service_token.result
}

resource "google_cloud_run_v2_service" "coordinator" {
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
        name  = "RALLY_ENABLE_CLOUD_TRACE"
        value = "1"
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
  ]
}

resource "google_cloud_run_v2_service_iam_member" "invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.coordinator.name
  role     = "roles/run.invoker"
  member   = var.invoker_member
}
