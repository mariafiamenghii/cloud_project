# Shared base of the API. Each person adds their own routes in their own file
# (events_api.tf, purchase.tf, workflow.tf, ...) using aws_apigatewayv2_api.http.

resource "aws_apigatewayv2_api" "http" {
  name          = "${var.prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
  }
}

# Checks the Cognito login token on every route that uses it.
resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.http.id
  authorizer_type  = "JWT"
  name             = "cognito"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.web.id]
    issuer   = "https://cognito-idp.${var.region}.amazonaws.com/${aws_cognito_user_pool.main.id}"
  }
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
}

# POST /admin/users/role (needs a valid login token; the Lambda also checks the admin group)
# Body: {"email": "...", "group": "fan|artist|admin"}
data "archive_file" "admin_set_role" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/admin_set_role"
  output_path = "${path.module}/admin_set_role.zip"
}

resource "aws_lambda_function" "admin_set_role" {
  function_name    = "${var.prefix}-admin-set-role"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.admin_set_role.output_path
  source_code_hash = data.archive_file.admin_set_role.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      USER_POOL_ID = aws_cognito_user_pool.main.id
    }
  }
}

resource "aws_apigatewayv2_integration" "admin_set_role" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.admin_set_role.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "admin_set_role" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /admin/users/role"
  target             = "integrations/${aws_apigatewayv2_integration.admin_set_role.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_lambda_permission" "admin_set_role" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.admin_set_role.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
