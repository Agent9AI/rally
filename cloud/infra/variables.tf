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

variable "image_uri" {
  description = "Immutable coordinator image URI; unused during bootstrap."
  type        = string
}

variable "deploy_service" {
  description = "Create Cloud Run only after the immutable image has been pushed."
  type        = bool
  default     = false
}

variable "invoker_member" {
  description = "Only principal allowed through Cloud Run IAM."
  type        = string
  default     = "user:imterryim@gmail.com"
}
