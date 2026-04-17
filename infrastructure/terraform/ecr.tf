# ECR Repositorios para las imágenes Docker
# axon-server (Rust) y axon-enterprise (Python)

# ECR Repository para axon-server (Rust runtime)
resource "aws_ecr_repository" "axon_server" {
  name                 = "axon/axon-server"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.project_name}-axon-server-repo"
  }
}

# Lifecycle policy para axon-server: retener últimas 10 imágenes
resource "aws_ecr_lifecycle_policy" "axon_server" {
  repository = aws_ecr_repository.axon_server.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus     = "any"
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# ECR Repository para axon-enterprise (Python sidecar)
resource "aws_ecr_repository" "axon_enterprise" {
  name                 = "axon/axon-enterprise"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Name = "${var.project_name}-axon-enterprise-repo"
  }
}

# Lifecycle policy para axon-enterprise: retener últimas 10 imágenes
resource "aws_ecr_lifecycle_policy" "axon_enterprise" {
  repository = aws_ecr_repository.axon_enterprise.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus     = "any"
          countType     = "imageCountMoreThan"
          countNumber   = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
