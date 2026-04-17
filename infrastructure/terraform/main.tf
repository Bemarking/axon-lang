terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.40"
    }
  }

  # Backend S3 para almacenamiento remoto del state
  # Crear el bucket MANUALMENTE antes del primer terraform init:
  #   aws s3 mb s3://axon-terraform-state-${ACCOUNT_ID} --region us-east-1
  #   aws s3api put-bucket-versioning \
  #     --bucket axon-terraform-state-${ACCOUNT_ID} \
  #     --versioning-configuration Status=Enabled
  #   aws dynamodb create-table --table-name axon-terraform-locks \
  #     --attribute-definitions AttributeName=LockID,AttributeType=S \
  #     --key-schema AttributeName=LockID,KeyType=HASH \
  #     --billing-mode PAY_PER_REQUEST --region us-east-1
  backend "s3" {
    bucket         = "axon-terraform-state-908489016816"
    key            = "axon/prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "axon-terraform-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region

  # Tags por defecto para todos los recursos creados por Terraform
  default_tags {
    tags = {
      Project     = "axon-enterprise"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# Data sources para información dinámica de AWS
data "aws_caller_identity" "current" {}

data "aws_availability_zones" "available" {
  state = "available"
}
