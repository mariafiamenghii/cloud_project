# OWNER: person E. CloudWatch dashboard for the demo and the load test.
# Open it in the AWS console: CloudWatch -> Dashboards -> <prefix>-dashboard

locals {
  fn_names = [
    aws_lambda_function.list_events.function_name,
    aws_lambda_function.create_event.function_name,
    aws_lambda_function.preferences.function_name,
    aws_lambda_function.recommend.function_name,
  ]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.prefix}-dashboard"

  dashboard_body = <<-EOT
  {
    "widgets": [
      {
        "type": "metric", "x": 0, "y": 0, "width": 12, "height": 6,
        "properties": {
          "title": "API requests (total, 4xx, 5xx)",
          "region": "${var.region}", "view": "timeSeries", "stat": "Sum", "period": 60,
          "metrics": [
            ["AWS/ApiGateway", "Count", "ApiId", "${aws_apigatewayv2_api.http.id}"],
            ["AWS/ApiGateway", "4xx", "ApiId", "${aws_apigatewayv2_api.http.id}"],
            ["AWS/ApiGateway", "5xx", "ApiId", "${aws_apigatewayv2_api.http.id}"]
          ]
        }
      },
      {
        "type": "metric", "x": 12, "y": 0, "width": 12, "height": 6,
        "properties": {
          "title": "API latency (ms)",
          "region": "${var.region}", "view": "timeSeries", "period": 60,
          "metrics": [
            ["AWS/ApiGateway", "Latency", "ApiId", "${aws_apigatewayv2_api.http.id}", {"stat": "Average", "label": "average"}],
            ["AWS/ApiGateway", "Latency", "ApiId", "${aws_apigatewayv2_api.http.id}", {"stat": "p95", "label": "p95"}]
          ]
        }
      },
      {
        "type": "metric", "x": 0, "y": 6, "width": 8, "height": 6,
        "properties": {
          "title": "Lambda invocations",
          "region": "${var.region}", "view": "timeSeries", "stat": "Sum", "period": 60,
          "metrics": [
            ["AWS/Lambda", "Invocations", "FunctionName", "${local.fn_names[0]}"],
            ["AWS/Lambda", "Invocations", "FunctionName", "${local.fn_names[1]}"],
            ["AWS/Lambda", "Invocations", "FunctionName", "${local.fn_names[2]}"],
            ["AWS/Lambda", "Invocations", "FunctionName", "${local.fn_names[3]}"]
          ]
        }
      },
      {
        "type": "metric", "x": 8, "y": 6, "width": 8, "height": 6,
        "properties": {
          "title": "Lambda errors and throttles",
          "region": "${var.region}", "view": "timeSeries", "stat": "Sum", "period": 60,
          "metrics": [
            ["AWS/Lambda", "Errors", "FunctionName", "${local.fn_names[0]}"],
            ["AWS/Lambda", "Errors", "FunctionName", "${local.fn_names[1]}"],
            ["AWS/Lambda", "Errors", "FunctionName", "${local.fn_names[2]}"],
            ["AWS/Lambda", "Errors", "FunctionName", "${local.fn_names[3]}"],
            ["AWS/Lambda", "Throttles", "FunctionName", "${local.fn_names[0]}"],
            ["AWS/Lambda", "Throttles", "FunctionName", "${local.fn_names[3]}"]
          ]
        }
      },
      {
        "type": "metric", "x": 16, "y": 6, "width": 8, "height": 6,
        "properties": {
          "title": "Lambda duration p95 (ms)",
          "region": "${var.region}", "view": "timeSeries", "stat": "p95", "period": 60,
          "metrics": [
            ["AWS/Lambda", "Duration", "FunctionName", "${local.fn_names[0]}"],
            ["AWS/Lambda", "Duration", "FunctionName", "${local.fn_names[1]}"],
            ["AWS/Lambda", "Duration", "FunctionName", "${local.fn_names[2]}"],
            ["AWS/Lambda", "Duration", "FunctionName", "${local.fn_names[3]}"]
          ]
        }
      }
    ]
  }
  EOT
}

output "dashboard_name" {
  value = aws_cloudwatch_dashboard.main.dashboard_name
}
