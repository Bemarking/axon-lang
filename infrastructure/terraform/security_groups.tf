# Security Groups
# ALB: ingress HTTP/HTTPS desde cualquier lugar
# ECS Tasks: ingress desde ALB (8420) + VPC interna (8080), egress todo
# RDS: ingress solo desde ECS tasks (5432)

# ============================================================================
# Security Group para ALB
# ============================================================================

resource "aws_security_group" "alb" {
  name        = "${var.project_name}-${var.environment}-alb-sg"
  description = "Security group para ALB"
  vpc_id      = aws_vpc.axon.id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-alb-sg"
  }
}

# ============================================================================
# Security Group para ECS Tasks
# ============================================================================

resource "aws_security_group" "ecs_tasks" {
  name        = "${var.project_name}-${var.environment}-ecs-tasks-sg"
  description = "Security group para ECS tasks"
  vpc_id      = aws_vpc.axon.id

  ingress {
    from_port       = 8420
    to_port         = 8420
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
    description     = "Axon server (Rust) desde ALB"
  }

  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "Axon enterprise (Python) desde VPC interna"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-ecs-tasks-sg"
  }
}

# ============================================================================
# Security Group para RDS
# ============================================================================

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-${var.environment}-rds-sg"
  description = "Security group para RDS PostgreSQL"
  vpc_id      = aws_vpc.axon.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_tasks.id]
    description     = "PostgreSQL desde ECS tasks"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Allow all outbound traffic"
  }

  tags = {
    Name = "${var.project_name}-${var.environment}-rds-sg"
  }
}
