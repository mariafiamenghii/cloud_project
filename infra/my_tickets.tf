# ------------------------------------------------
# MY TICKETS
# GET /orders -> the logged-in buyer's own orders and ticket QR codes.
# Reads the orders "by-user" index, so it only ever returns the caller's orders.
# ------------------------------------------------
data "archive_file" "list_orders" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/list_orders/index.py"
  output_path = "${path.module}/list_orders.zip"
}

resource "aws_lambda_function" "list_orders" {
  function_name    = "${var.prefix}-list-orders"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.list_orders.output_path
  source_code_hash = data.archive_file.list_orders.output_base64sha256
  timeout          = 15

  environment {
    variables = {
      ORDERS_TABLE  = aws_dynamodb_table.orders.name
      TICKETS_TABLE = aws_dynamodb_table.tickets.name
      EVENTS_TABLE  = aws_dynamodb_table.events.name
    }
  }
}

resource "aws_apigatewayv2_integration" "list_orders" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.list_orders.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "list_orders" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "GET /orders"
  target             = "integrations/${aws_apigatewayv2_integration.list_orders.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_lambda_permission" "list_orders" {
  statement_id  = "AllowAPIGatewayListOrders"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.list_orders.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/GET/orders"
}
