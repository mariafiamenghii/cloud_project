# ------------------------------------------------
# SELF-HEALING FOR THE PURCHASE WORKER
# When the Academy lab stops, LabRole briefly loses its SQS permissions and Lambda
# disables the queue trigger of the purchase worker. It stays disabled after the
# lab restarts. EventBridge runs a small Lambda every 5 minutes that re-enables
# that one trigger, unless purchases are paused on purpose (maintenance flag).
#
# Pause the worker for a migration (set the flag FIRST, then disable):
#   aws ssm put-parameter --name /ticketing/purchase-worker/maintenance --value on --overwrite
#   aws lambda update-event-source-mapping --uuid <uuid> --no-enabled
# Resume: set the flag back to "off"; the trigger is re-enabled within 5 minutes.
# ------------------------------------------------

# Operators change the value with the CLI; Terraform only creates the parameter.
resource "aws_ssm_parameter" "purchase_worker_maintenance" {
  name        = "/${var.prefix}/purchase-worker/maintenance"
  description = "on = keep the purchase worker queue trigger disabled (migration); off = self-heal it"
  type        = "String"
  value       = "off"

  lifecycle {
    ignore_changes = [value]
  }
}

data "archive_file" "heal_worker" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/heal_worker/index.py"
  output_path = "${path.module}/heal_worker.zip"
}

resource "aws_cloudwatch_log_group" "heal_worker" {
  name              = "/aws/lambda/${var.prefix}-heal-worker"
  retention_in_days = 14
}

resource "aws_lambda_function" "heal_worker" {
  function_name    = "${var.prefix}-heal-worker"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.heal_worker.output_path
  source_code_hash = data.archive_file.heal_worker.output_base64sha256
  timeout          = 30
  memory_size      = 128

  environment {
    variables = {
      WORKER_FUNCTION_NAME  = aws_lambda_function.purchase_worker.function_name
      MAPPING_UUID          = aws_lambda_event_source_mapping.purchase_queue_trigger.uuid
      QUEUE_ARN             = aws_sqs_queue.purchase_queue.arn
      QUEUE_URL             = aws_sqs_queue.purchase_queue.url
      MAINTENANCE_PARAMETER = aws_ssm_parameter.purchase_worker_maintenance.name
    }
  }

  depends_on = [aws_cloudwatch_log_group.heal_worker]
}

resource "aws_cloudwatch_event_rule" "heal_worker" {
  name                = "${var.prefix}-heal-worker"
  description         = "Every 5 minutes, re-enable the purchase worker queue trigger if the lab disabled it"
  schedule_expression = "rate(5 minutes)"
}

resource "aws_cloudwatch_event_target" "heal_worker" {
  rule = aws_cloudwatch_event_rule.heal_worker.name
  arn  = aws_lambda_function.heal_worker.arn
}

resource "aws_lambda_permission" "heal_worker" {
  statement_id  = "AllowEventBridgeHealWorker"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.heal_worker.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.heal_worker.arn
}
