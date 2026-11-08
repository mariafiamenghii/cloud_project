
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
      DRY_RUN = "true"
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
