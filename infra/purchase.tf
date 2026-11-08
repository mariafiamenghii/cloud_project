
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
