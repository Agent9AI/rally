variable "project_id" {
  description = "Google Cloud project that owns Rally's coordinator."
  type        = string
  default     = "rally-agent9-2026"
}

variable "region" {
  description = "Cloud Run and Artifact Registry region."
  type        = string
  default     = "us-east1"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "rally-google-coordinator"
}

variable "a2a_base_url" {
  description = "Stable external base URL advertised by Rally's A2A Agent Card."
  type        = string
  default     = "https://rally-google-coordinator-u5xngrbzna-ue.a.run.app"
}

variable "image_uri" {
  description = "Immutable coordinator image URI; unused during bootstrap."
  type        = string
}

variable "deploy_service" {
  description = "Create Cloud Run only after the immutable image has been pushed."
  type        = bool
  default     = false
}

variable "operator_member" {
  description = "Human allowed to mint short-lived tokens as the local invoker identity."
  type        = string
  default     = "user:imterryim@gmail.com"
}
