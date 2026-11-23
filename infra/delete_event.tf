# ------------------------------------------------
# DELETE EVENTS
# DELETE /events/{eventId} -> an artist deletes their own event, an admin any event.
# Events with sales are refused by the Lambda.
# ------------------------------------------------
data "archive_file" "delete_event" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/delete_event/index.py"
  output_path = "${path.module}/delete_event.zip"
}

resource "aws_lambda_function" "delete_event" {
  function_name    = "${var.prefix}-delete-event"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.delete_event.output_path
  source_code_hash = data.archive_file.delete_event.output_base64sha256
  timeout          = 15

  environment {
    variables = {
      EVENTS_TABLE = aws_dynamodb_table.events.name
      ORDERS_TABLE = aws_dynamodb_table.orders.name
    }
  }
}

resource "aws_apigatewayv2_integration" "delete_event" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.delete_event.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "delete_event" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "DELETE /events/{eventId}"
  target             = "integrations/${aws_apigatewayv2_integration.delete_event.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_lambda_permission" "delete_event" {
  statement_id  = "AllowAPIGatewayDeleteEvent"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.delete_event.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/DELETE/events/*"
}
