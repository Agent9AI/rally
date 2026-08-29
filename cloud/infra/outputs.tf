output "service_url" {
  description = "IAM-protected Rally coordinator URL."
  value       = try(google_cloud_run_v2_service.coordinator[0].uri, null)
}

output "service_account" {
  description = "Least-privilege Cloud Run runtime identity."
  value       = google_service_account.coordinator.email
}

output "artifact_repository" {
  description = "Container repository resource name."
  value       = google_artifact_registry_repository.rally.name
}

output "local_token_install_command" {
  description = "Run after apply to mirror the service token into macOS Keychain."
  value       = "security add-generic-password -U -s rally-cloud-token -a rally -w \"$(gcloud secrets versions access latest --secret=rally-cloud-service-token --project=${var.project_id})\""
}
