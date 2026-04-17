# RDS PostgreSQL Database
# Resides en private subnets, accesible solo desde ECS tasks y no desde internet
# Multi-AZ para alta disponibilidad en producción

resource "random_password" "rds_password" {
  length  = 32
  special = true
}

resource "aws_db_subnet_group" "axon" {
  name       = "${var.project_name}-${var.environment}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${var.project_name}-${var.environment}-db-subnet-group"
  }
}

resource "aws_db_instance" "axon" {
  # Identificadores
  identifier     = "${var.project_name}-${var.environment}-db"
  engine         = "postgres"
  engine_version = "14"

  # Clase de instancia y almacenamiento
  instance_class       = var.rds_instance_class
  allocated_storage    = var.rds_allocated_storage_gb
  max_allocated_storage = var.rds_max_allocated_storage_gb
  storage_type         = "gp3"
  storage_encrypted    = true

  # Database inicial
  db_name  = var.rds_db_name
  username = var.rds_username
  password = random_password.rds_password.result

  # Networking
  db_subnet_group_name   = aws_db_subnet_group.axon.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  # Backup y mantenimiento
  backup_retention_period = var.rds_backup_retention_days
  backup_window           = "03:00-04:00"
  maintenance_window      = "mon:04:00-mon:05:00"

  # Alta disponibilidad
  multi_az = var.rds_multi_az

  # Performance y logging
  enabled_cloudwatch_logs_exports = ["postgresql"]
  performance_insights_enabled     = true
  deletion_protection              = var.environment == "prod" ? true : false

  skip_final_snapshot       = var.environment != "prod"
  final_snapshot_identifier = "${var.project_name}-${var.environment}-final-snapshot-${formatdate("YYYY-MM-DD-hhmm", timestamp())}"

  tags = {
    Name = "${var.project_name}-${var.environment}-db"
  }

  depends_on = [aws_security_group.rds]
}

# Almacenar la password en Secrets Manager para referencia segura
resource "aws_secretsmanager_secret_version" "rds_password" {
  secret_id     = aws_secretsmanager_secret.rds_password.id
  secret_string = random_password.rds_password.result
}

resource "aws_secretsmanager_secret" "rds_password" {
  name                    = "${var.project_name}/${var.environment}/RDS_PASSWORD"
  recovery_window_in_days = 7

  tags = {
    Name = "${var.project_name}-${var.environment}-rds-password"
  }
}
