# Secrets Manager Secrets
# DATABASE_URL: construida a partir del endpoint RDS
# Auth token y LLM API keys: inicializadas con placeholder "REPLACE_ME"

# ============================================================================
# DATABASE_URL Secret
# ============================================================================

resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${var.project_name}/${var.environment}/DATABASE_URL"
  recovery_window_in_days = 7

  tags = {
    Name = "${var.project_name}-${var.environment}-database-url"
  }
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql://${var.rds_username}:${random_password.rds_password.result}@${aws_db_instance.axon.address}:${aws_db_instance.axon.port}/${var.rds_db_name}?sslmode=require"
}

# ============================================================================
# AXON_AUTH_TOKEN Secret
# ============================================================================

resource "aws_secretsmanager_secret" "axon_auth_token" {
  name                    = "${var.project_name}/${var.environment}/AXON_AUTH_TOKEN"
  recovery_window_in_days = 7

  tags = {
    Name = "${var.project_name}-${var.environment}-axon-auth-token"
  }
}

resource "random_password" "axon_auth_token" {
  length  = 48
  special = true
}

resource "aws_secretsmanager_secret_version" "axon_auth_token" {
  secret_id     = aws_secretsmanager_secret.axon_auth_token.id
  secret_string = random_password.axon_auth_token.result
}

# ============================================================================
# LLM API Keys Secrets (inicialmente "REPLACE_ME")
# ============================================================================

resource "aws_secretsmanager_secret" "anthropic_api_key" {
  name                    = "${var.project_name}/${var.environment}/ANTHROPIC_API_KEY"
  recovery_window_in_days = 7

  tags = {
    Name = "${var.project_name}-${var.environment}-anthropic-api-key"
  }
}

resource "aws_secretsmanager_secret_version" "anthropic_api_key" {
  secret_id     = aws_secretsmanager_secret.anthropic_api_key.id
  secret_string = "REPLACE_ME"
}

resource "aws_secretsmanager_secret" "openai_api_key" {
  name                    = "${var.project_name}/${var.environment}/OPENAI_API_KEY"
  recovery_window_in_days = 7

  tags = {
    Name = "${var.project_name}-${var.environment}-openai-api-key"
  }
}

resource "aws_secretsmanager_secret_version" "openai_api_key" {
  secret_id     = aws_secretsmanager_secret.openai_api_key.id
  secret_string = "REPLACE_ME"
}

resource "aws_secretsmanager_secret" "gemini_api_key" {
  name                    = "${var.project_name}/${var.environment}/GEMINI_API_KEY"
  recovery_window_in_days = 7

  tags = {
    Name = "${var.project_name}-${var.environment}-gemini-api-key"
  }
}

resource "aws_secretsmanager_secret_version" "gemini_api_key" {
  secret_id     = aws_secretsmanager_secret.gemini_api_key.id
  secret_string = "REPLACE_ME"
}

resource "aws_secretsmanager_secret" "openrouter_api_key" {
  name                    = "${var.project_name}/${var.environment}/OPENROUTER_API_KEY"
  recovery_window_in_days = 7

  tags = {
    Name = "${var.project_name}-${var.environment}-openrouter-api-key"
  }
}

resource "aws_secretsmanager_secret_version" "openrouter_api_key" {
  secret_id     = aws_secretsmanager_secret.openrouter_api_key.id
  secret_string = "REPLACE_ME"
}
