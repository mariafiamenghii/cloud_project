variable "region" {
  description = "AWS Region allowed by the lab (usually us-east-1)"
  type        = string
  default     = "us-east-1"
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
  description = "GitHub token for the initial Amplify repository connection"
  type        = string
  sensitive   = true
  default     = null
}