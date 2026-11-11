
# OWNER: Person C - Purchase system
# SQS queues for processing ticket purchase requests.

# Dead-Letter Queue: stores messages that repeatedly fail.
resource "aws_sqs_queue" "purchase_dlq" {
  name                      = "${var.prefix}-purchase-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

# Main queue: stores incoming purchase requests.
resource "aws_sqs_queue" "purchase_queue" {
  name                       = "${var.prefix}-purchase-queue"
  visibility_timeout_seconds = 180
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
  source_file = "${path.module}/../lambdas/purchase_worker/index.py"
  output_path = "${path.module}/purchase_worker.zip"
}

# Lambda function that processes SQS messages
resource "aws_lambda_function" "purchase_worker" {
  function_name = "${var.prefix}-purchase-worker"

  role    = data.aws_iam_role.lab.arn
  runtime = "python3.12"
  handler = "index.lambda_handler"

  filename         = data.archive_file.purchase_worker.output_path
  source_code_hash = data.archive_file.purchase_worker.output_base64sha256

  timeout     = 30
  memory_size = 128

  environment {
    variables = {
      ORDERS_TABLE = aws_dynamodb_table.orders.name
      WORKFLOW_ARN = var.purchase_workflow_arn
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

# Part D is intentionally not referenced until the branches are integrated.
# Supply the unqualified ARN of its STANDARD state machine; no workflow is
# created by Part C. An empty ARN fails closed in the worker (never dry-runs).
variable "purchase_workflow_arn" {
  description = "Unqualified ARN of Part D's STANDARD purchase workflow; configure before sending purchases."
  type        = string
  default     = ""

  validation {
    condition = (
      var.purchase_workflow_arn == "" ||
      can(regex("^arn:[a-z0-9-]+:states:[a-z0-9-]+:[0-9]{12}:stateMachine:[A-Za-z0-9_-]+$", var.purchase_workflow_arn))
    )
    error_message = "Use an unqualified Step Functions state machine ARN, or an empty value before integration."
  }
}

data "archive_file" "create_purchase" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/create_purchase/index.py"
  output_path = "${path.module}/create_purchase.zip"
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
