variable "region" {
  description = "AWS Region allowed by the lab (usually us-east-1)"
  type        = string
  default     = "us-east-1"
}

variable "purchases_enabled" {
  description = "Pause purchase intake during a reviewed inventory migration."
  type        = bool
  default     = true
}

variable "prefix" {
  description = "Prefix for every resource name"
  type        = string
  default     = "ticketing"
}

variable "lab_role_name" {
  description = "Existing IAM role that Academy accounts let us reuse (we cannot create roles)"
  type        = string
  default     = "LabRole"
}

variable "github_access_token" {
  description = "GitHub token supplied locally through TF_VAR_github_access_token, never committed"
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = length(trimspace(var.github_access_token)) > 0
    error_message = "Supply the GitHub token through TF_VAR_github_access_token before planning or applying."
  }
}
variable "notify_email" {
  description = "Email address for SES confirmation emails. Must be a VERIFIED SES identity (sandbox sends only to verified addresses). The workflow sends FROM and TO this same address."
  type        = string
  default     = ""
}
