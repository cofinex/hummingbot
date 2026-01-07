#!/bin/bash
# AWS Fargate Deployment Script for Hummingbot

set -e

# Configuration
AWS_REGION=${AWS_REGION:-us-east-1}
ENVIRONMENT=${ENVIRONMENT:-production}
ECR_REPOSITORY=${ECR_REPOSITORY:-hummingbot}
IMAGE_TAG=${IMAGE_TAG:-latest}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING: $1${NC}"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $1${NC}"
    exit 1
}

# Check prerequisites
check_prerequisites() {
    log "Checking prerequisites..."

    # Check AWS CLI
    if ! command -v aws &> /dev/null; then
        error "AWS CLI is not installed"
    fi

    # Check Docker
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed"
    fi

    # Check Terraform
    if ! command -v terraform &> /dev/null; then
        error "Terraform is not installed"
    fi

    # Check AWS credentials
    if ! aws sts get-caller-identity &> /dev/null; then
        error "AWS credentials not configured"
    fi

    log "Prerequisites check passed"
}

# Build and push Docker image
build_and_push_image() {
    log "Building and pushing Docker image..."

    # Get AWS account ID
    AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
    ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPOSITORY}"

    # Create ECR repository if it doesn't exist
    aws ecr describe-repositories --repository-names ${ECR_REPOSITORY} --region ${AWS_REGION} || \
    aws ecr create-repository --repository-name ${ECR_REPOSITORY} --region ${AWS_REGION}

    # Login to ECR
    aws ecr get-login-password --region ${AWS_REGION} | docker login --username AWS --password-stdin ${ECR_URI}

    # Build image
    docker build -f Dockerfile.fargate -t ${ECR_REPOSITORY}:${IMAGE_TAG} .

    # Tag image
    docker tag ${ECR_REPOSITORY}:${IMAGE_TAG} ${ECR_URI}:${IMAGE_TAG}

    # Push image
    docker push ${ECR_URI}:${IMAGE_TAG}

    log "Image pushed to ECR: ${ECR_URI}:${IMAGE_TAG}"
}

# Deploy infrastructure
deploy_infrastructure() {
    log "Deploying infrastructure with Terraform..."

    cd terraform

    # Initialize Terraform
    terraform init

    # Plan deployment
    terraform plan -var="aws_region=${AWS_REGION}" -var="environment=${ENVIRONMENT}"

    # Apply deployment
    terraform apply -var="aws_region=${AWS_REGION}" -var="environment=${ENVIRONMENT}" -auto-approve

    # Get outputs
    VPC_ID=$(terraform output -raw vpc_id)
    EFS_ID=$(terraform output -raw efs_file_system_id)
    S3_BUCKET=$(terraform output -raw s3_bucket_name)
    ECS_CLUSTER=$(terraform output -raw ecs_cluster_name)

    log "Infrastructure deployed successfully"
    log "VPC ID: ${VPC_ID}"
    log "EFS ID: ${EFS_ID}"
    log "S3 Bucket: ${S3_BUCKET}"
    log "ECS Cluster: ${ECS_CLUSTER}"

    cd ..
}

# Store secrets in Parameter Store
store_secrets() {
    log "Storing secrets in Parameter Store..."

    # MQTT configuration
    read -p "Enter MQTT broker host: " MQTT_HOST
    read -p "Enter MQTT username: " MQTT_USERNAME
    read -s -p "Enter MQTT password: " MQTT_PASSWORD
    echo

    # Store secrets
    aws ssm put-parameter --name "/hummingbot/mqtt/host" --value "${MQTT_HOST}" --type "String" --overwrite
    aws ssm put-parameter --name "/hummingbot/mqtt/username" --value "${MQTT_USERNAME}" --type "String" --overwrite
    aws ssm put-parameter --name "/hummingbot/mqtt/password" --value "${MQTT_PASSWORD}" --type "SecureString" --overwrite

    log "Secrets stored in Parameter Store"
}

# Upload strategy files to S3
upload_strategies() {
    log "Uploading strategy files to S3..."

    S3_BUCKET=$(cd terraform && terraform output -raw s3_bucket_name)

    # Upload strategy files
    if [ -d "conf/strategies" ]; then
        aws s3 sync conf/strategies/ s3://${S3_BUCKET}/strategies/
    fi

    # Upload script strategies
    if [ -d "scripts" ]; then
        aws s3 sync scripts/ s3://${S3_BUCKET}/scripts/
    fi

    log "Strategy files uploaded to S3"
}

# Deploy ECS service
deploy_service() {
    log "Deploying ECS service..."

    ECS_CLUSTER=$(cd terraform && terraform output -raw ecs_cluster_name)

    # Update service
    aws ecs update-service --cluster ${ECS_CLUSTER} --service ${ENVIRONMENT}-hummingbot-service --force-new-deployment

    # Wait for deployment to complete
    aws ecs wait services-stable --cluster ${ECS_CLUSTER} --services ${ENVIRONMENT}-hummingbot-service

    log "ECS service deployed successfully"
}

# Setup monitoring
setup_monitoring() {
    log "Setting up monitoring..."

    # Install monitoring dependencies
    pip install paho-mqtt boto3 requests

    # Start monitoring (in background)
    nohup python monitoring/monitor.py > monitoring/monitor.log 2>&1 &

    log "Monitoring setup complete"
}

# Main deployment function
main() {
    log "Starting Hummingbot deployment to AWS Fargate..."

    check_prerequisites
    build_and_push_image
    deploy_infrastructure
    store_secrets
    upload_strategies
    deploy_service
    setup_monitoring

    log "Deployment completed successfully!"
    log "Check CloudWatch logs for bot status"
    log "Use MQTT client to send commands to the bot"
}

# Run main function
main "$@"
