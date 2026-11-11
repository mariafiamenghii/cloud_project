# OWNER: person D (workflow, ticket, email).
# Purchase fulfillment with atomic seat/order transitions and safe compensation.
# Each Lambda packages the shared helper; all functions reuse the lab role.

data "archive_file" "reserve_seat" {
  type = "zip"
  source {
    content  = file("${path.module}/../lambdas/reserve_seat/index.py")
    filename = "index.py"
  }
  source {
    content  = file("${path.module}/../lambdas/workflow_common/purchase_common.py")
    filename = "purchase_common.py"
  }
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
      ORDERS_TABLE = aws_dynamodb_table.orders.name
      SEATS_TABLE  = aws_dynamodb_table.seats.name
      EVENTS_TABLE = aws_dynamodb_table.events.name
      HOLD_SECONDS = "900"
    }
  }
}

data "archive_file" "take_payment" {
  type = "zip"
  source {
    content  = file("${path.module}/../lambdas/take_payment/index.py")
    filename = "index.py"
  }
  source {
    content  = file("${path.module}/../lambdas/workflow_common/purchase_common.py")
    filename = "purchase_common.py"
  }
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

  environment {
    variables = {
      ORDERS_TABLE = aws_dynamodb_table.orders.name
      SEATS_TABLE  = aws_dynamodb_table.seats.name
    }
  }
}

data "archive_file" "generate_ticket" {
  type = "zip"
  source {
    content  = file("${path.module}/../lambdas/generate_ticket/index.py")
    filename = "index.py"
  }
  source {
    content  = file("${path.module}/../lambdas/workflow_common/purchase_common.py")
    filename = "purchase_common.py"
  }
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
  type = "zip"
  source {
    content  = file("${path.module}/../lambdas/send_email/index.py")
    filename = "index.py"
  }
  source {
    content  = file("${path.module}/../lambdas/workflow_common/purchase_common.py")
    filename = "purchase_common.py"
  }
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
      ORDERS_TABLE = aws_dynamodb_table.orders.name
    }
  }
}

data "archive_file" "release_seat" {
  type = "zip"
  source {
    content  = file("${path.module}/../lambdas/release_seat/index.py")
    filename = "index.py"
  }
  source {
    content  = file("${path.module}/../lambdas/workflow_common/purchase_common.py")
    filename = "purchase_common.py"
  }
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
      SEATS_TABLE  = aws_dynamodb_table.seats.name
      ORDERS_TABLE = aws_dynamodb_table.orders.name
    }
  }
}

# SES sandbox identity: the workflow sends FROM and TO this verified address.
resource "aws_ses_email_identity" "notify" {
  email = var.notify_email
}

# Retry infrastructure errors, not business rejections such as SeatUnavailable.
locals {
  purchase_task_retry = [{
    ErrorEquals = [
      "Lambda.ServiceException", "Lambda.AWSLambdaException", "Lambda.SdkClientException",
      "Lambda.TooManyRequestsException", "Sandbox.Timedout", "States.Timeout",
      "ClientError", "ReadTimeoutError", "ConnectTimeoutError", "EndpointConnectionError",
      "ConnectionClosedError", "ConcurrentOrderChange",
    ]
    IntervalSeconds = 1
    MaxAttempts     = 2
    BackoffRate     = 2.0
  }]
}

resource "aws_sfn_state_machine" "purchase" {
  name     = "${var.prefix}-purchase-workflow"
  type     = "STANDARD"
  role_arn = data.aws_iam_role.lab.arn

  definition = jsonencode({
    Comment        = "Idempotent purchase fulfillment with atomic inventory and durable failure states"
    StartAt        = "ReserveSeat"
    TimeoutSeconds = 300
    States = {
      ReserveSeat = {
        Type           = "Task"
        Resource       = aws_lambda_function.reserve_seat.arn
        TimeoutSeconds = 20
        ResultPath     = "$.reserve"
        Retry          = local.purchase_task_retry
        Catch          = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "RejectOrder" }]
        Next           = "TakePayment"
      }
      TakePayment = {
        Type           = "Task"
        Resource       = aws_lambda_function.take_payment.arn
        TimeoutSeconds = 20
        ResultPath     = "$.payment"
        Retry          = local.purchase_task_retry
        Catch          = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "ReleaseSeat" }]
        Next           = "GenerateTicket"
      }
      GenerateTicket = {
        Type           = "Task"
        Resource       = aws_lambda_function.generate_ticket.arn
        TimeoutSeconds = 20
        ResultPath     = "$"
        Retry          = local.purchase_task_retry
        Catch          = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "ReviewOrder" }]
        Next           = "SendEmail"
      }
      SendEmail = {
        Type           = "Task"
        Resource       = aws_lambda_function.send_email.arn
        TimeoutSeconds = 20
        ResultPath     = "$.email"
        Retry          = local.purchase_task_retry
        Catch          = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "RecordNotificationFailure" }]
        Next           = "Succeeded"
      }
      RejectOrder = {
        Type           = "Task"
        Resource       = aws_lambda_function.release_seat.arn
        TimeoutSeconds = 20
        Parameters     = { "order.$" = "$", failureStage = "RESERVATION" }
        ResultPath     = "$.failure"
        Retry          = local.purchase_task_retry
        Next           = "ReservationFailed"
      }
      ReleaseSeat = {
        Type           = "Task"
        Resource       = aws_lambda_function.release_seat.arn
        TimeoutSeconds = 20
        Parameters     = { "order.$" = "$", failureStage = "PAYMENT" }
        ResultPath     = "$.failure"
        Retry          = local.purchase_task_retry
        Next           = "PaymentFailed"
      }
      ReviewOrder = {
        Type           = "Task"
        Resource       = aws_lambda_function.release_seat.arn
        TimeoutSeconds = 20
        Parameters     = { "order.$" = "$", failureStage = "FULFILLMENT" }
        ResultPath     = "$.failure"
        Retry          = local.purchase_task_retry
        Next           = "FulfillmentFailed"
      }
      RecordNotificationFailure = {
        Type           = "Task"
        Resource       = aws_lambda_function.release_seat.arn
        TimeoutSeconds = 20
        Parameters     = { "order.$" = "$", failureStage = "NOTIFICATION" }
        ResultPath     = "$.email"
        Retry          = local.purchase_task_retry
        Next           = "Succeeded"
      }
      Succeeded = { Type = "Succeed" }
      ReservationFailed = {
        Type  = "Fail"
        Error = "ReservationFailed"
        Cause = "Reservation rejected or failed; inspect the persisted order"
      }
      PaymentFailed = {
        Type  = "Fail"
        Error = "PaymentFailed"
        Cause = "Payment failed or its outcome requires review; inspect the persisted order"
      }
      FulfillmentFailed = {
        Type  = "Fail"
        Error = "FulfillmentFailed"
        Cause = "Paid purchase requires reconciliation; inventory was not released"
      }
    }
  })
}
