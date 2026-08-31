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

variable "workspace_id" {
  description = "Stable non-secret workspace identifier shared by approved Rally administrators."
  type        = string
  default     = "agent9-rally"

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$", var.workspace_id))
    error_message = "workspace_id must be 1-96 safe identifier characters."
  }
}

variable "trial_email_domain" {
  description = "Rally-owned domain shown only for temporary evaluation identities."
  type        = string
  default     = "updates.agent9.dev"

  validation {
    condition = (
      length(var.trial_email_domain) <= 253 &&
      length(split(".", var.trial_email_domain)) >= 2 &&
      alltrue([
        for label in split(".", var.trial_email_domain) :
        can(regex("^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$", label))
      ])
    )
    error_message = "trial_email_domain must be a valid fully qualified domain name."
  }
}

variable "pilot_email_address" {
  description = "Existing live pilot address assigned to this configured workspace; empty disables the shortcut."
  type        = string
  default     = "rally@updates.agent9.dev"

  validation {
    condition = (
      var.pilot_email_address == "" ||
      try(
        length(split("@", var.pilot_email_address)) == 2 &&
        can(regex("^[A-Za-z0-9]([A-Za-z0-9._-]{0,62}[A-Za-z0-9])?$", split("@", var.pilot_email_address)[0])) &&
        length(split("@", var.pilot_email_address)[1]) <= 253 &&
        length(split(".", split("@", var.pilot_email_address)[1])) >= 2 &&
        alltrue([
          for label in split(".", split("@", var.pilot_email_address)[1]) :
          can(regex("^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$", label))
        ]),
        false
      )
    )
    error_message = "pilot_email_address must be empty or a valid email address."
  }
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
  default = [
    "imterryim@gmail.com",
    "terry@agent9.dev",
  ]
}

variable "operator_member" {
  description = "Human allowed to mint short-lived tokens as the local invoker identity."
  type        = string
  default     = "user:imterryim@gmail.com"
}
