# OWNER: person E. Taste survey + recommendations.
# POST /preferences  saves the survey (needs login)
# GET  /preferences  reads it back (needs login)
# GET  /recommendations  top 10 events for the logged-in user (needs login)

data "archive_file" "preferences" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/preferences"
  output_path = "${path.module}/preferences.zip"
}

resource "aws_lambda_function" "preferences" {
  function_name    = "${var.prefix}-preferences"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.preferences.output_path
  source_code_hash = data.archive_file.preferences.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      PREFS_TABLE = aws_dynamodb_table.preferences.name
    }
  }
}

data "archive_file" "recommend" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/recommend"
  output_path = "${path.module}/recommend.zip"
}

resource "aws_lambda_function" "recommend" {
  function_name    = "${var.prefix}-recommend"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.recommend.output_path
  source_code_hash = data.archive_file.recommend.output_base64sha256
  timeout          = 15

  environment {
    variables = {
      EVENTS_TABLE = aws_dynamodb_table.events.name
      PREFS_TABLE  = aws_dynamodb_table.preferences.name
    }
  }
}

resource "aws_apigatewayv2_integration" "preferences" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.preferences.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_integration" "recommend" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.recommend.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "post_preferences" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /preferences"
  target             = "integrations/${aws_apigatewayv2_integration.preferences.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_route" "get_preferences" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /preferences"
  target             = "integrations/${aws_apigatewayv2_integration.preferences.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_route" "get_recommendations" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /recommendations"
  target             = "integrations/${aws_apigatewayv2_integration.recommend.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_lambda_permission" "preferences" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.preferences.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

resource "aws_lambda_permission" "recommend" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.recommend.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
