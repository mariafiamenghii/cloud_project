# OWNER: person D (workflow, ticket, email).
# Purchase-fulfillment Step Functions workflow: ReserveSeat -> TakePayment ->
# GenerateTicket -> SendEmail, with a Catch on payment failure that releases
# the held seat. Every Lambda and the state machine reuse the lab role.

data "archive_file" "reserve_seat" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/reserve_seat"
  output_path = "${path.module}/reserve_seat.zip"
}

resource "aws_lambda_function" "reserve_seat" {
  function_name    = "${var.prefix}-reserve-seat"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.reserve_seat.output_path
  source_code_hash = data.archive_file.reserve_seat.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      SEATS_TABLE  = aws_dynamodb_table.seats.name
      EVENTS_TABLE = aws_dynamodb_table.events.name
      HOLD_SECONDS = "900"
    }
  }
}

data "archive_file" "take_payment" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/take_payment"
  output_path = "${path.module}/take_payment.zip"
}

resource "aws_lambda_function" "take_payment" {
  function_name    = "${var.prefix}-take-payment"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.take_payment.output_path
  source_code_hash = data.archive_file.take_payment.output_base64sha256
  timeout          = 10
}

data "archive_file" "generate_ticket" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/generate_ticket"
  output_path = "${path.module}/generate_ticket.zip"
}

resource "aws_lambda_function" "generate_ticket" {
  function_name    = "${var.prefix}-generate-ticket"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.generate_ticket.output_path
  source_code_hash = data.archive_file.generate_ticket.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      ORDERS_TABLE = aws_dynamodb_table.orders.name
      SEATS_TABLE  = aws_dynamodb_table.seats.name
    }
  }
}

data "archive_file" "send_email" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/send_email"
  output_path = "${path.module}/send_email.zip"
}

resource "aws_lambda_function" "send_email" {
  function_name    = "${var.prefix}-send-email"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.send_email.output_path
  source_code_hash = data.archive_file.send_email.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      NOTIFY_EMAIL = var.notify_email
    }
  }
}

data "archive_file" "release_seat" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/release_seat"
  output_path = "${path.module}/release_seat.zip"
}

resource "aws_lambda_function" "release_seat" {
  function_name    = "${var.prefix}-release-seat"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.release_seat.output_path
  source_code_hash = data.archive_file.release_seat.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      SEATS_TABLE = aws_dynamodb_table.seats.name
    }
  }
}

# SES sandbox identity: the workflow sends FROM and TO this verified address.
# Only created when a notify_email is set. SES is blocked on the AWS Academy
# and Innovation Sandbox accounts, so creating it unconditionally made
# `terraform apply` fail for everyone with AccessDenied. With no email, the
# send_email Lambda just records emailStatus=not_sent and the purchase still
# completes.
resource "aws_ses_email_identity" "notify" {
  count = var.notify_email != "" ? 1 : 0
  email = var.notify_email
}

resource "aws_sfn_state_machine" "purchase" {
  name     = "${var.prefix}-purchase-workflow"
  type     = "STANDARD"
  role_arn = data.aws_iam_role.lab.arn

  definition = jsonencode({
    Comment = "Purchase fulfillment: reserve -> pay -> ticket -> email, release seat on payment failure"
    StartAt = "ReserveSeat"
    States = {
      ReserveSeat = {
        Type       = "Task"
        Resource   = aws_lambda_function.reserve_seat.arn
        ResultPath = "$.reserve"
        Retry      = [{ ErrorEquals = ["States.TaskFailed"], IntervalSeconds = 1, MaxAttempts = 2, BackoffRate = 2.0 }]
        Next       = "TakePayment"
      }
      TakePayment = {
        Type       = "Task"
        Resource   = aws_lambda_function.take_payment.arn
        ResultPath = "$.payment"
        Retry      = [{ ErrorEquals = ["States.Timeout"], IntervalSeconds = 1, MaxAttempts = 1, BackoffRate = 2.0 }]
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "ReleaseSeat" }]
        Next       = "GenerateTicket"
      }
      GenerateTicket = {
        Type = "Task"
        # ResultPath "$" so the ticket fields (qrPayload, qrUrl) returned
        # alongside the order become top-level state for SendEmail to read.
        Resource   = aws_lambda_function.generate_ticket.arn
        ResultPath = "$"
        Next       = "SendEmail"
      }
      SendEmail = {
        Type       = "Task"
        Resource   = aws_lambda_function.send_email.arn
        ResultPath = "$.email"
        Next       = "Succeeded"
      }
      Succeeded = { Type = "Succeed" }
      ReleaseSeat = {
        Type       = "Task"
        Resource   = aws_lambda_function.release_seat.arn
        ResultPath = "$.release"
        Next       = "MarkFailed"
      }
      MarkFailed = {
        Type  = "Fail"
        Error = "PaymentFailed"
        Cause = "Payment failed; seat released"
      }
    }
  })
}
