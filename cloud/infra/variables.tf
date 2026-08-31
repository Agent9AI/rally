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
  description = "Digest-pinned coordinator image URI; unused during bootstrap."
  type        = string
}

variable "control_plane_image_uri" {
  description = "Digest-pinned control-plane image URI; defaults to image_uri when omitted."
  type        = string
  default     = ""
}

variable "deploy_service" {
  description = "Create Cloud Run only after the immutable image has been pushed."
  type        = bool
  default     = false
}

variable "deploy_control_plane" {
  description = "Create the public user-authenticated control-plane service."
  type        = bool
  default     = false
}

variable "control_plane_service_name" {
  description = "Public Cloud Run service that owns customer identity and connections."
  type        = string
  default     = "rally-control-plane"
}

variable "google_web_client_id" {
  description = "Public Google Identity Services web client ID accepted by Rally."
  type        = string
  default     = ""

  validation {
    condition = (
      var.google_web_client_id == "" ||
      can(regex("^[0-9]+-[A-Za-z0-9_-]+\\.apps\\.googleusercontent\\.com$", var.google_web_client_id))
    )
    error_message = "google_web_client_id must be empty or a Google OAuth web client ID."
  }
}

variable "google_workspace_client_id" {
  description = "Dedicated confidential OAuth client ID for the aggregate Google Workspace connector."
  type        = string
  default     = ""

  validation {
    condition = (
      var.google_workspace_client_id == "" ||
      can(regex("^[0-9]+-[A-Za-z0-9_-]+\\.apps\\.googleusercontent\\.com$", var.google_workspace_client_id))
    )
    error_message = "google_workspace_client_id must be empty or a Google OAuth web client ID."
  }
}

variable "control_plane_allowed_origins" {
  description = "Exact browser origins permitted to call the public control plane."
  type        = list(string)
  default     = ["https://rally.agent9.dev"]
}

variable "control_plane_allowed_user_emails" {
  description = "Initial account allowlist; explicitly pass an empty list only for a deliberate public launch."
  type        = list(string)
  default     = ["imterryim@gmail.com"]
}

variable "operator_member" {
  description = "Human allowed to mint short-lived tokens as the local invoker identity."
  type        = string
  default     = "user:imterryim@gmail.com"
}
