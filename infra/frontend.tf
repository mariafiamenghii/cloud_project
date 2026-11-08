
# OWNER: Part A - Frontend and Amplify Hosting

resource "aws_amplify_app" "frontend" {
  name     = "${var.prefix}-frontend"
  platform = "WEB"

  repository   = "https://github.com/mariafiamenghii/cloud_project"
  access_token = var.github_access_token

  # This repository contains both backend and frontend code.
  # Amplify must build only the web/ directory.
  environment_variables = {
    AMPLIFY_MONOREPO_APP_ROOT = "web"

    VITE_AWS_REGION      = var.region
    VITE_USER_POOL_ID    = aws_cognito_user_pool.main.id
    VITE_USER_POOL_CLIENT_ID = aws_cognito_user_pool_client.web.id
    VITE_API_URL         = aws_apigatewayv2_api.http.api_endpoint
  }

  build_spec = <<-YAML
    version: 1
    applications:
      - appRoot: web
        frontend:
          phases:
            preBuild:
              commands:
                - npm ci
            build:
              commands:
                - npm run build
          artifacts:
            baseDirectory: dist
            files:
              - '**/*'
          cache:
            paths:
              - node_modules/**/*
  YAML

  # Support React Router navigation.
  custom_rule {
    source = "</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|ttf|map|json)$)([^.]+$)/>"
    target = "/index.html"
    status = "200"
  }
}

# The final deployment tracks the team's main branch.
resource "aws_amplify_branch" "main" {
  app_id      = aws_amplify_app.frontend.id
  branch_name = "main"
  stage       = "PRODUCTION"

  enable_auto_build = true
}

output "frontend_url" {
  description = "Public URL of the React website"
  value = "https://${aws_amplify_branch.main.branch_name}.${aws_amplify_app.frontend.default_domain}"
}
