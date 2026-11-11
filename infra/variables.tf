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

variable "notify_email" {
  description = "Email address for SES confirmation emails. Must be a VERIFIED SES identity (sandbox sends only to verified addresses). The workflow sends FROM and TO this same address."
  type        = string
  default     = ""
}
