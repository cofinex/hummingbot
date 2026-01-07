# AWS Fargate + Hummingbot + MQTT Infrastructure
terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Variables
variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

variable "mqtt_broker_type" {
  description = "MQTT broker type: iot-core or ec2"
  type        = string
  default     = "iot-core"
}

# Data sources
data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_caller_identity" "current" {}

# VPC
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name = "${var.environment}-hummingbot-vpc"
  }
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "${var.environment}-hummingbot-igw"
  }
}

# Public Subnets
resource "aws_subnet" "public" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${count.index + 1}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]

  map_public_ip_on_launch = true

  tags = {
    Name = "${var.environment}-hummingbot-public-${count.index + 1}"
    Type = "Public"
  }
}

# Private Subnets
resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.${count.index + 10}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]

  tags = {
    Name = "${var.environment}-hummingbot-private-${count.index + 1}"
    Type = "Private"
  }
}

# NAT Gateway
resource "aws_eip" "nat" {
  count  = 2
  domain = "vpc"

  tags = {
    Name = "${var.environment}-hummingbot-nat-${count.index + 1}"
  }
}

resource "aws_nat_gateway" "main" {
  count         = 2
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name = "${var.environment}-hummingbot-nat-${count.index + 1}"
  }

  depends_on = [aws_internet_gateway.main]
}

# Route Tables
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name = "${var.environment}-hummingbot-public-rt"
  }
}

resource "aws_route_table" "private" {
  count  = 2
  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index].id
  }

  tags = {
    Name = "${var.environment}-hummingbot-private-rt-${count.index + 1}"
  }
}

# Route Table Associations
resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

# Security Groups
resource "aws_security_group" "hummingbot" {
  name_prefix = "${var.environment}-hummingbot-"
  vpc_id      = aws_vpc.main.id

  # Health check
  ingress {
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  # MQTT
  egress {
    from_port   = 1883
    to_port     = 1883
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 8883
    to_port     = 8883
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS for API calls
  egress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTP for API calls
  egress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # NFS for EFS
  egress {
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  tags = {
    Name = "${var.environment}-hummingbot-sg"
  }
}

# EFS File System
resource "aws_efs_file_system" "hummingbot" {
  creation_token = "${var.environment}-hummingbot-efs"
  encrypted      = true

  tags = {
    Name = "${var.environment}-hummingbot-efs"
  }
}

resource "aws_efs_mount_target" "hummingbot" {
  count           = 2
  file_system_id  = aws_efs_file_system.hummingbot.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}

resource "aws_security_group" "efs" {
  name_prefix = "${var.environment}-efs-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "${var.environment}-efs-sg"
  }
}

# S3 Bucket for strategy files
resource "aws_s3_bucket" "hummingbot" {
  bucket = "${var.environment}-hummingbot-strategies-${random_string.bucket_suffix.result}"

  tags = {
    Name = "${var.environment}-hummingbot-strategies"
  }
}

resource "random_string" "bucket_suffix" {
  length  = 8
  special = false
  upper   = false
}

resource "aws_s3_bucket_versioning" "hummingbot" {
  bucket = aws_s3_bucket.hummingbot.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_encryption" "hummingbot" {
  bucket = aws_s3_bucket.hummingbot.id

  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "AES256"
      }
    }
  }
}

# IAM Role for ECS Task
resource "aws_iam_role" "ecs_task_execution_role" {
  name = "${var.environment}-hummingbot-ecs-task-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_role_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task_role" {
  name = "${var.environment}-hummingbot-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

# IAM Policy for S3 access
resource "aws_iam_policy" "s3_access" {
  name = "${var.environment}-hummingbot-s3-access"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = "${aws_s3_bucket.hummingbot.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = aws_s3_bucket.hummingbot.arn
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "s3_access" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.s3_access.arn
}

# IAM Policy for Parameter Store access
resource "aws_iam_policy" "parameter_store_access" {
  name = "${var.environment}-hummingbot-parameter-store-access"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:GetParameters",
          "ssm:GetParametersByPath"
        ]
        Resource = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/hummingbot/*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "parameter_store_access" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.parameter_store_access.arn
}

# ECS Cluster
resource "aws_ecs_cluster" "hummingbot" {
  name = "${var.environment}-hummingbot-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Name = "${var.environment}-hummingbot-cluster"
  }
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "hummingbot" {
  name              = "/ecs/${var.environment}-hummingbot"
  retention_in_days = 30

  tags = {
    Name = "${var.environment}-hummingbot-logs"
  }
}

# ECS Task Definition
resource "aws_ecs_task_definition" "hummingbot" {
  family                   = "${var.environment}-hummingbot"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = 1024
  memory                   = 2048
  execution_role_arn       = aws_iam_role.ecs_task_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name  = "hummingbot"
      image = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com/${var.environment}-hummingbot:latest"

      essential = true

      portMappings = [
        {
          containerPort = 8080
          protocol      = "tcp"
        }
      ]

      environment = [
        {
          name  = "HEADLESS_MODE"
          value = "true"
        },
        {
          name  = "AWS_REGION"
          value = var.aws_region
        },
        {
          name  = "EFS_MOUNT_PATH"
          value = "/mnt/efs"
        }
      ]

      secrets = [
        {
          name      = "MQTT_HOST"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/hummingbot/mqtt/host"
        },
        {
          name      = "MQTT_PASSWORD"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/hummingbot/mqtt/password"
        },
        {
          name      = "MQTT_USERNAME"
          valueFrom = "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/hummingbot/mqtt/username"
        }
      ]

      mountPoints = [
        {
          sourceVolume  = "efs-storage"
          containerPath = "/mnt/efs"
          readOnly      = false
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.hummingbot.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command = [
          "CMD-SHELL",
          "curl -f http://localhost:8080/health || exit 1"
        ]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 60
      }
    }
  ])

  volume {
    name = "efs-storage"

    efs_volume_configuration {
      file_system_id          = aws_efs_file_system.hummingbot.id
      root_directory          = "/"
      transit_encryption      = "ENABLED"
      transit_encryption_port = 2049

      authorization_config {
        access_point_id = aws_efs_access_point.hummingbot.id
        iam             = "ENABLED"
      }
    }
  }

  tags = {
    Name = "${var.environment}-hummingbot-task"
  }
}

# EFS Access Point
resource "aws_efs_access_point" "hummingbot" {
  file_system_id = aws_efs_file_system.hummingbot.id

  posix_user {
    gid = 1000
    uid = 1000
  }

  root_directory {
    path = "/hummingbot"
    creation_info {
      owner_gid   = 1000
      owner_uid   = 1000
      permissions = "755"
    }
  }

  tags = {
    Name = "${var.environment}-hummingbot-access-point"
  }
}

# ECS Service
resource "aws_ecs_service" "hummingbot" {
  name            = "${var.environment}-hummingbot-service"
  cluster         = aws_ecs_cluster.hummingbot.id
  task_definition = aws_ecs_task_definition.hummingbot.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.hummingbot.id]
    assign_public_ip = false
  }

  depends_on = [
    aws_efs_mount_target.hummingbot
  ]

  tags = {
    Name = "${var.environment}-hummingbot-service"
  }
}

# Outputs
output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs"
  value       = aws_subnet.private[*].id
}

output "efs_file_system_id" {
  description = "EFS file system ID"
  value       = aws_efs_file_system.hummingbot.id
}

output "s3_bucket_name" {
  description = "S3 bucket name for strategies"
  value       = aws_s3_bucket.hummingbot.bucket
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.hummingbot.name
}
