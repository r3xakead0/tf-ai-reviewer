# Minimal demo config for a personal AWS sandbox. This exists only so we
# have something to open test pull requests against -- it is not meant to
# represent production-quality Terraform.

terraform {
  required_version = ">= 1.13"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.6"
    }
  }

  # Local backend keeps this demo self-contained -- no remote state backend
  # to provision before you can open a test PR.
  backend "local" {
    path = "terraform.tfstate"
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_s3_bucket" "sandbox" {
  bucket = "${var.project_name}-sandbox-${var.environment}"

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_security_group" "sandbox" {
  name        = "${var.project_name}-sandbox-sg"
  description = "Sandbox security group for demo workloads"

  # Intentionally permissive (0.0.0.0/0 SSH) so there's a real finding for
  # the AI reviewer to catch when you open a test PR that touches this file.
  ingress {
    description = "SSH from anywhere (demo only -- not for real use)"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}

resource "aws_iam_role" "sandbox" {
  name = "${var.project_name}-sandbox-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Project     = var.project_name
    Environment = var.environment
  }
}
