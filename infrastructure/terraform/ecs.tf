# ECS Cluster y Task Definition
# 2 containers en same task: axon-server (Rust, essential=true) + axon-enterprise (Python, essential=false)
# Fargate con 2048 CPU / 4096 MB memory

resource "aws_ecs_cluster" "axon" {
  name = "${var.project_name}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-cluster"
  }
}

# ============================================================================
# CloudWatch Log Groups
# ============================================================================

resource "aws_cloudwatch_log_group" "axon_server" {
  name              = "/ecs/${var.project_name}-${var.environment}/axon-server"
  retention_in_days = 30

  tags = {
    Name = "${var.project_name}-${var.environment}-axon-server-logs"
  }
}

resource "aws_cloudwatch_log_group" "axon_enterprise" {
  name              = "/ecs/${var.project_name}-${var.environment}/axon-enterprise"
  retention_in_days = 30

  tags = {
    Name = "${var.project_name}-${var.environment}-axon-enterprise-logs"
  }
}

# ============================================================================
# ECS Task Definition
# ============================================================================

resource "aws_ecs_task_definition" "axon" {
  family                   = "${var.project_name}-${var.environment}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.task_cpu
  memory                   = var.task_memory_mb
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      # Container 1: axon-server (Rust runtime) — ESSENTIAL
      name      = "axon-server"
      image     = "${aws_ecr_repository.axon_server.repository_url}:latest"
      essential = true
      cpu       = var.rust_server_cpu
      memory    = var.rust_server_memory_mb

      portMappings = [
        {
          containerPort = 8420
          hostPort      = 8420
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "AXON_HOST"
          value = "0.0.0.0"
        },
        {
          name  = "AXON_PORT"
          value = "8420"
        },
        {
          name  = "RUST_LOG"
          value = "info,axon=debug"
        },
        {
          name  = "LOG_FORMAT"
          value = "json"
        }
      ]

      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = aws_secretsmanager_secret.database_url.arn
        },
        {
          name      = "AXON_AUTH_TOKEN"
          valueFrom = aws_secretsmanager_secret.axon_auth_token.arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.axon_server.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8420/v1/health/live || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 60
      }
    },
    {
      # Container 2: axon-enterprise (Python sidecar) — NON-ESSENTIAL
      name      = "axon-enterprise"
      image     = "${aws_ecr_repository.axon_enterprise.repository_url}:latest"
      essential = false
      cpu       = var.python_sidecar_cpu
      memory    = var.python_sidecar_memory_mb

      portMappings = [
        {
          containerPort = 8080
          hostPort      = 8080
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "AXON_HOST"
          value = "0.0.0.0"
        },
        {
          name  = "AXON_PORT"
          value = "8080"
        },
        {
          name  = "AXON_SERVER_URL"
          value = "http://localhost:8420"
        }
      ]

      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = aws_secretsmanager_secret.database_url.arn
        },
        {
          name      = "AXON_AUTH_TOKEN"
          valueFrom = aws_secretsmanager_secret.axon_auth_token.arn
        },
        {
          name      = "ANTHROPIC_API_KEY"
          valueFrom = aws_secretsmanager_secret.anthropic_api_key.arn
        },
        {
          name      = "OPENAI_API_KEY"
          valueFrom = aws_secretsmanager_secret.openai_api_key.arn
        },
        {
          name      = "GEMINI_API_KEY"
          valueFrom = aws_secretsmanager_secret.gemini_api_key.arn
        },
        {
          name      = "OPENROUTER_API_KEY"
          valueFrom = aws_secretsmanager_secret.openrouter_api_key.arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.axon_enterprise.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:8080/v1/health || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 20
      }

      dependsOn = [
        {
          containerName = "axon-server"
          condition     = "HEALTHY"
        }
      ]
    }
  ])

  tags = {
    Name = "${var.project_name}-${var.environment}-task-definition"
  }

  depends_on = [
    aws_cloudwatch_log_group.axon_server,
    aws_cloudwatch_log_group.axon_enterprise,
    aws_secretsmanager_secret.database_url,
    aws_secretsmanager_secret.axon_auth_token
  ]
}

# ============================================================================
# ECS Service
# ============================================================================

resource "aws_ecs_service" "axon" {
  name            = "${var.project_name}-${var.environment}"
  cluster         = aws_ecs_cluster.axon.id
  task_definition = aws_ecs_task_definition.axon.arn
  desired_count   = var.ecs_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.axon.arn
    container_name   = "axon-server"
    container_port   = 8420
  }

  health_check_grace_period_seconds = 120

  tags = {
    Name = "${var.project_name}-${var.environment}-service"
  }

  depends_on = [
    aws_lb_listener.http,
    aws_iam_role_policy.ecs_task_execution_secrets
  ]
}
