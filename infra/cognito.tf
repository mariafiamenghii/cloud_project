# OWNER: person B (login and roles).

resource "aws_cognito_user_pool" "main" {
  name                     = "${var.prefix}-users"
  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 8
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = false
  }

  # After a user confirms their sign-up, put them in the "fan" group.
  lambda_config {
    post_confirmation = aws_lambda_function.post_confirmation.arn
  }
}

# The three roles. The group name travels inside the login token.
resource "aws_cognito_user_group" "groups" {
  for_each     = toset(["fan", "artist", "admin"])
  name         = each.key
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cognito_user_pool_client" "web" {
  name            = "${var.prefix}-web"
  user_pool_id    = aws_cognito_user_pool.main.id
  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_PASSWORD_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]
}

# Every new user starts in the "fan" group (an admin can change it later).
data "archive_file" "post_confirmation" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/post_confirmation"
  output_path = "${path.module}/post_confirmation.zip"
}

resource "aws_lambda_function" "post_confirmation" {
  function_name    = "${var.prefix}-post-confirmation"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.post_confirmation.output_path
  source_code_hash = data.archive_file.post_confirmation.output_base64sha256
  timeout          = 10
}

resource "aws_lambda_permission" "post_confirmation" {
  statement_id  = "AllowCognito"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.post_confirmation.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.main.arn
}
