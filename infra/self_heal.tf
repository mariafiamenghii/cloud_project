# ------------------------------------------------
# SELF-HEALING FOR THE PURCHASE WORKER
# EventBridge runs a small Lambda every 5 minutes. If the queue trigger of the
# purchase worker has been disabled (it happens after the lab is restarted), the
# Lambda turns it back on so waiting purchases are processed.
# ------------------------------------------------
data "archive_file" "heal_worker" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/heal_worker/index.py"
  output_path = "${path.module}/heal_worker.zip"
}

resource "aws_lambda_function" "heal_worker" {
  function_name    = "${var.prefix}-heal-worker"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.heal_worker.output_path
  source_code_hash = data.archive_file.heal_worker.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      WORKER_FUNCTION_NAME = aws_lambda_function.purchase_worker.function_name
    }
  }
}

resource "aws_cloudwatch_event_rule" "heal_worker" {
  name                = "${var.prefix}-heal-worker"
  description         = "Check every 5 minutes that the purchase worker queue trigger is enabled"
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
