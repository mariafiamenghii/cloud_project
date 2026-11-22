# ------------------------------------------------
# ARTIST SALES
# GET /my-events -> sales summary of the events created by the logged-in artist.
# The Lambda also checks the artist/admin group, like create_event.
# ------------------------------------------------
data "archive_file" "list_my_events" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/list_my_events/index.py"
  output_path = "${path.module}/list_my_events.zip"
}

resource "aws_lambda_function" "list_my_events" {
  function_name    = "${var.prefix}-list-my-events"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.list_my_events.output_path
  source_code_hash = data.archive_file.list_my_events.output_base64sha256
  timeout          = 15

  environment {
    variables = {
      EVENTS_TABLE = aws_dynamodb_table.events.name
    }
  }
}

resource "aws_apigatewayv2_integration" "list_my_events" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.list_my_events.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "list_my_events" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /my-events"
  target             = "integrations/${aws_apigatewayv2_integration.list_my_events.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_lambda_permission" "list_my_events" {
  statement_id  = "AllowAPIGatewayListMyEvents"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.list_my_events.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/GET/my-events"
}
