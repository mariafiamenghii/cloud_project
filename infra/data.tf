data "aws_caller_identity" "me" {}

# Academy accounts usually cannot create IAM roles, so every Lambda,
# Step Functions state machine, etc. reuses this existing role.
data "aws_iam_role" "lab" {
  name = var.lab_role_name
}
