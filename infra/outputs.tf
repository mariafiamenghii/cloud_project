output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "region" {
  value = var.region
}

output "workflow_arn" {
  value = aws_sfn_state_machine.purchase.arn
}
