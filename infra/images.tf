# Raw uploads and validated images remain private. Only associated event images
# are served by the read Lambda; no public bucket policy or extra IAM grants.
resource "aws_s3_bucket" "event_images" {
  bucket = "${var.prefix}-event-images-${data.aws_caller_identity.me.account_id}"
  lifecycle { prevent_destroy = true }
}

resource "aws_s3_bucket_public_access_block" "event_images" {
  bucket                  = aws_s3_bucket.event_images.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "event_images" {
  bucket = aws_s3_bucket.event_images.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "event_images" {
  bucket = aws_s3_bucket.event_images.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_cors_configuration" "event_images" {
  bucket = aws_s3_bucket.event_images.id
  cors_rule {
    allowed_origins = ["https://main.${aws_amplify_app.frontend.default_domain}"]
    allowed_methods = ["POST"]
    allowed_headers = ["content-type"]
    max_age_seconds = 300
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "event_images" {
  bucket = aws_s3_bucket.event_images.id
  rule {
    id     = "expire-unpublished-uploads"
    status = "Enabled"
    filter { prefix = "uploads/" }
    expiration { days = 1 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

resource "aws_lambda_layer_version" "image_validation" {
  layer_name          = "${var.prefix}-image-validation"
  filename            = "${path.module}/image_validation_layer.zip"
  source_code_hash    = filebase64sha256("${path.module}/image_validation_layer.zip")
  compatible_runtimes = ["python3.12"]
}

data "archive_file" "event_images" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/event_images"
  excludes    = ["__pycache__/**", "*.pyc"]
  output_path = "${path.module}/event_images.zip"
}

resource "aws_lambda_function" "event_images" {
  function_name    = "${var.prefix}-event-images"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "index.handler"
  filename         = data.archive_file.event_images.output_path
  source_code_hash = data.archive_file.event_images.output_base64sha256
  timeout          = 10
  memory_size      = 256
  environment {
    variables = {
      EVENTS_TABLE  = aws_dynamodb_table.events.name
      IMAGES_BUCKET = aws_s3_bucket.event_images.id
    }
  }
}

resource "aws_apigatewayv2_integration" "event_images" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.event_images.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "image_upload" {
  api_id             = aws_apigatewayv2_api.http.id
  route_key          = "POST /event-images/uploads"
  target             = "integrations/${aws_apigatewayv2_integration.event_images.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_route" "event_image" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /event-images/{eventId}"
  target    = "integrations/${aws_apigatewayv2_integration.event_images.id}"
}

resource "aws_lambda_permission" "event_images" {
  statement_id  = "AllowAPIGatewayImages"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.event_images.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*/event-images/*"
}
