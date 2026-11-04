# First working slice: list events (public) and create events (artists only).
# Copy this pattern for every new Lambda + route.

data "archive_file" "list_events" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/list_events"
  output_path = "${path.module}/list_events.zip"
}

resource "aws_lambda_function" "list_events" {
  function_name    = "${var.prefix}-list-events"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.list_events.output_path
  source_code_hash = data.archive_file.list_events.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      EVENTS_TABLE = aws_dynamodb_table.events.name
    }
  }
}

data "archive_file" "create_event" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/create_event"
  output_path = "${path.module}/create_event.zip"
}

resource "aws_lambda_function" "create_event" {
  function_name    = "${var.prefix}-create-event"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.create_event.output_path
  source_code_hash = data.archive_file.create_event.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      EVENTS_TABLE = aws_dynamodb_table.events.name
    }
  }
}

# GET /events (anyone can browse)
resource "aws_apigatewayv2_integration" "list_events" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.list_events.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "list_events" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /events"
  target    = "integrations/${aws_apigatewayv2_integration.list_events.id}"
}

resource "aws_lambda_permission" "list_events" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.list_events.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# POST /events (needs a valid login token; the Lambda also checks the artist group)
resource "aws_apigatewayv2_integration" "create_event" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.create_event.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "create_event" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /events"
  target             = "integrations/${aws_apigatewayv2_integration.create_event.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_lambda_permission" "create_event" {
  statement_id  = "AllowAPIGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.create_event.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}
