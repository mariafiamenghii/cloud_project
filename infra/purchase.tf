
# OWNER: Person C - Purchase system
# SQS queues for processing ticket purchase requests.

locals {
  purchase_worker_timeout_seconds = 30
}

# Dead-Letter Queue: stores messages that repeatedly fail.
resource "aws_sqs_queue" "purchase_dlq" {
  name                      = "${var.prefix}-purchase-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

# Main queue: stores incoming purchase requests.
resource "aws_sqs_queue" "purchase_queue" {
  name = "${var.prefix}-purchase-queue"
  # Lambda recommends six times the function timeout for a zero batch window.
  visibility_timeout_seconds = 6 * local.purchase_worker_timeout_seconds
  message_retention_seconds  = 345600 # 4 days
  receive_wait_time_seconds  = 20
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.purchase_dlq.arn
    maxReceiveCount     = 5
  })
}


# ------------------------------------------------
# PURCHASE WORKER - AWS Lambda
# ------------------------------------------------

# Package the Python code into a ZIP for Lambda
data "archive_file" "purchase_worker" {
  type        = "zip"
  output_path = "${path.module}/purchase_worker.zip"

  source {
    content  = file("${path.module}/../lambdas/purchase_worker/index.py")
    filename = "index.py"
  }

  source {
    content  = file("${path.module}/../lambdas/purchase_dispatch.py")
    filename = "purchase_dispatch.py"
  }
}

# Lambda function that processes SQS messages
resource "aws_lambda_function" "purchase_worker" {
  function_name = "${var.prefix}-purchase-worker"

  role    = data.aws_iam_role.lab.arn
  runtime = "python3.12"
  handler = "index.lambda_handler"

  filename         = data.archive_file.purchase_worker.output_path
  source_code_hash = data.archive_file.purchase_worker.output_base64sha256

  timeout     = local.purchase_worker_timeout_seconds
  memory_size = 128

  environment {
    variables = {
      ORDERS_TABLE = aws_dynamodb_table.orders.name
      WORKFLOW_ARN = aws_sfn_state_machine.purchase.arn
    }
  }
}

# ------------------------------------------------
# CONNECT SQS TO LAMBDA
# ------------------------------------------------

resource "aws_lambda_event_source_mapping" "purchase_queue_trigger" {
  event_source_arn = aws_sqs_queue.purchase_queue.arn
  function_name    = aws_lambda_function.purchase_worker.arn

  batch_size = 1
  enabled    = true

  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = 2
  }
}

data "archive_file" "create_purchase" {
  type        = "zip"
  output_path = "${path.module}/create_purchase.zip"

  source {
    content  = file("${path.module}/../lambdas/create_purchase/index.py")
    filename = "index.py"
  }

  source {
    content  = file("${path.module}/../lambdas/purchase_dispatch.py")
    filename = "purchase_dispatch.py"
  }
}

resource "aws_lambda_function" "create_purchase" {
  function_name    = "${var.prefix}-create-purchase"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.create_purchase.output_path
  source_code_hash = data.archive_file.create_purchase.output_base64sha256
  timeout          = 10
  memory_size      = 128

  environment {
    variables = {
      EVENTS_TABLE       = aws_dynamodb_table.events.name
      ORDERS_TABLE       = aws_dynamodb_table.orders.name
      PURCHASE_QUEUE_URL = aws_sqs_queue.purchase_queue.url
      WORKFLOW_ARN       = aws_sfn_state_machine.purchase.arn
    }
  }
}

resource "aws_apigatewayv2_integration" "create_purchase" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.create_purchase.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "create_purchase" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /purchases"
  target             = "integrations/${aws_apigatewayv2_integration.create_purchase.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_lambda_permission" "create_purchase" {
  statement_id  = "AllowAPIGatewayPurchases"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.create_purchase.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/POST/purchases"
}
