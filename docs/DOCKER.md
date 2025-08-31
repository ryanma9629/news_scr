# Adverse News Screening - Docker Deployment Guide

This guide provides comprehensive instructions for deploying the Adverse News Screening application using Docker.

## 📋 Prerequisites

- Docker Engine (version 20.10 or higher)
- Docker Compose (version 2.0 or higher)
- At least 4GB of available RAM
- API access to all required LLM providers:
  - Azure OpenAI API access (required)
  - DeepSeek API access (required)
  - Tongyi Qwen (DashScope) API access (required)

## 🚀 Quick Start

### 1. Clone and Setup

```bash
# Navigate to the project directory
cd /path/to/news_scr

# Make management scripts executable
chmod +x scripts/docker.sh scripts/build.sh

# Use the management script for easy deployment
./scripts/docker.sh build
./scripts/docker.sh start
```

### 2. Configure Environment

```bash
# Copy environment template
cp .env.example .env

# Edit with your API keys (required)
nano .env
```

**Required Environment Variables:**
- `AZURE_OPENAI_API_KEY`: Your Azure OpenAI API key
- `AZURE_OPENAI_ENDPOINT`: Your Azure OpenAI endpoint URL
- `OPENAI_API_VERSION`: API version (default: 2025-03-01-preview)
- `DEEPSEEK_API_KEY`: Your DeepSeek API key
- `DASHSCOPE_API_KEY`: Your Tongyi Qwen (DashScope) API key

### 3. Access Application

- **Web Interface**: http://localhost:8280
- **API Health Check**: http://localhost:8280/api/health
- **MongoDB**: localhost:27017
- **PostgreSQL**: localhost:5432

## 🏗 Services Overview

### adverse-news-screening
- **Port**: 8280
- **Description**: Main FastAPI application serving the adverse news screening interface
- **Health Check**: HTTP GET request to `/api/health` endpoint
- **Features**: Web search, content crawling, tagging, summarization, Q&A

### mongodb
- **Port**: 27017
- **Description**: MongoDB database for storing scraped content and metadata
- **Database**: `adverse_news_screening`
- **Collections**: `web_contents`, `fc_tags`
- **Persistence**: Data stored in Docker volume `mongodb_data`

### postgres
- **Port**: 5432
- **Description**: PostgreSQL database for storing tagging results
- **Database**: `adverse_news_screening`
- **Table**: `fc_tags`
- **Persistence**: Data stored in Docker volume `postgres_data`

## 📁 Docker Files Overview

| File | Purpose |
|------|---------|
| `docker/Dockerfile` | Main application container definition |
| `docker/docker-compose.yml` | Development deployment configuration |
| `docker/docker-compose.prod.yml` | Production deployment configuration |
| `.dockerignore` | Files excluded from Docker build context |
| `scripts/docker.sh` | Management script for common operations |
| `scripts/build.sh` | Simple build script |
| `.env.example` | Environment variables template |

## 🛠 Management Commands

Use the `scripts/docker.sh` script for easy management:

```bash
# Build the application
./scripts/docker.sh build

# Start services
./scripts/docker.sh start

# Stop services
./scripts/docker.sh stop

# Restart services
./scripts/docker.sh restart

# View logs (all services)
./scripts/docker.sh logs

# View logs (specific service)
./scripts/docker.sh logs adverse-news-screening
./scripts/docker.sh logs mongodb

# Check status
./scripts/docker.sh status

# Clean up (removes all data!)
./scripts/docker.sh clean
```

## 🔧 Manual Docker Commands

If you prefer manual control:

```bash
# Build and start
docker-compose -f docker/docker-compose.yml up -d

# View logs
docker-compose -f docker/docker-compose.yml logs -f

# Stop services
docker-compose -f docker/docker-compose.yml down

# Rebuild specific service
docker-compose -f docker/docker-compose.yml build adverse-news-screening

# Access service shell
docker-compose -f docker/docker-compose.yml exec adverse-news-screening bash
docker-compose -f docker/docker-compose.yml exec mongodb mongosh
```

## 🏭 Production Deployment

For production environments, use the production configuration:

```bash
# Use production compose file
docker-compose -f docker/docker-compose.prod.yml up -d

# Or with override
docker-compose -f docker/docker-compose.yml -f docker/docker-compose.prod.yml up -d
```

### Production Features

- **Resource limits**: Memory and CPU constraints
- **Health checks**: Proper dependency management
- **Logging**: Structured log rotation
- **Security**: Non-root user, read-only volumes
- **Monitoring**: Enhanced health check intervals

## 🔐 Security Configuration

### SSL/HTTPS Setup

1. **Generate SSL certificates** (if not already available):
```bash
python config/ssl/generate_ssl.py
```

2. **Configure SSL in environment**:
```bash
SSL_CERTFILE=cert.pem
SSL_KEYFILE=key.pem
```

3. **Access via HTTPS**:
```
https://localhost:8280
```

### MongoDB Authentication (Production)

For production, enable MongoDB authentication:

1. **Uncomment authentication variables** in `docker/docker-compose.prod.yml`:
```yaml
environment:
  - MONGO_INITDB_ROOT_USERNAME=${MONGO_ROOT_USERNAME}
  - MONGO_INITDB_ROOT_PASSWORD=${MONGO_ROOT_PASSWORD}
```

2. **Add to .env file**:
```bash
MONGO_ROOT_USERNAME=admin
MONGO_ROOT_PASSWORD=your_secure_password
MONGO_URI=mongodb://admin:your_secure_password@mongodb:27017/adverse_news_screening?authSource=admin
```

### Container Security

Additional security considerations:

- **Non-root user**: The application runs as a non-root user inside the container for enhanced security
- **Read-only volumes**: SSL certificates are mounted as read-only volumes
- **Environment isolation**: Environment variables should be kept secure and not committed to version control
- **Docker secrets**: Consider using Docker secrets in production environments for sensitive data
- **Network isolation**: Services communicate through Docker's internal network

## 🗃 Data Management

### Database Persistence

Database data is stored in Docker volumes:

**MongoDB:**
- `mongodb_data`: Database files
- `mongodb_config`: Configuration files

**PostgreSQL:**
- `postgres_data`: Database files
- `postgres_config`: Configuration files

### Backup and Restore

**MongoDB:**
```bash
# Backup database
docker-compose -f docker/docker-compose.yml exec mongodb mongodump --out /tmp/backup
docker cp $(docker-compose -f docker/docker-compose.yml ps -q mongodb):/tmp/backup ./backup

# Restore database
docker cp ./backup $(docker-compose -f docker/docker-compose.yml ps -q mongodb):/tmp/backup
docker-compose -f docker/docker-compose.yml exec mongodb mongorestore /tmp/backup
```

**PostgreSQL:**
```bash
# Backup database
docker-compose -f docker/docker-compose.yml exec postgres pg_dump -U postgres adverse_news_screening > ./backup/postgres_backup.sql

# Restore database
docker-compose -f docker/docker-compose.yml exec -T postgres psql -U postgres adverse_news_screening < ./backup/postgres_backup.sql
```

## 🐛 Troubleshooting

### Common Issues

1. **Port already in use**:
```bash
# Check what's using the port
sudo lsof -i :8280
sudo lsof -i :27017

# Change port in docker/docker-compose.yml or stop conflicting service
```

2. **MongoDB connection issues**:
```bash
# Check MongoDB logs
./scripts/docker.sh logs mongodb

# Verify MongoDB health
docker-compose -f docker/docker-compose.yml exec mongodb mongosh --eval "db.adminCommand('ping')"
```

3. **Application won't start**:
```bash
# Check application logs
./scripts/docker.sh logs adverse-news-screening

# Verify environment variables
docker-compose -f docker/docker-compose.yml exec adverse-news-screening env | grep -E "(AZURE|MONGO)"
```

4. **Memory issues**:
```bash
# Check Docker resource usage
docker stats

# Increase Docker memory limit in Docker Desktop settings
```

### Health Checks

Monitor service health:
```bash
# Check all services
docker-compose -f docker/docker-compose.yml ps

# Manual health check
curl http://localhost:8280/api/health
```

### Log Analysis

```bash
# Follow all logs
docker-compose -f docker/docker-compose.yml logs -f

# Filter by service
docker-compose -f docker/docker-compose.yml logs -f adverse-news-screening | grep ERROR

# Check MongoDB operations
docker-compose -f docker/docker-compose.yml logs mongodb | grep -E "(connection|error)"
```

## 🔧 Development

### Development Mode

Enable development features:

```bash
# Set in .env file
RELOAD=true

# Or override in docker-compose
docker-compose -f docker/docker-compose.yml run --rm -p 8280:8280 -e RELOAD=true adverse-news-screening
```

### Code Changes

For development with live reload:

```bash
# Mount source code
docker-compose -f docker/docker-compose.yml run --rm -p 8280:8280 -v $(pwd):/app adverse-news-screening python -m app.main
```

### Debugging

```bash
# Access application container
docker-compose -f docker/docker-compose.yml exec adverse-news-screening bash

# Check Python environment
docker-compose -f docker/docker-compose.yml exec adverse-news-screening python -c "import sys; print(sys.path)"

# Test database connection
docker-compose -f docker/docker-compose.yml exec adverse-news-screening python -c "from app.doc_store import MongoStore; store = MongoStore('test', 'en'); print('Connection OK')"
```

## 📊 Monitoring

### Application Metrics

The application provides several endpoints for monitoring:

- `/api/health`: Basic health check
- `/api/session/{session_id}/status`: Session status
- MongoDB metrics via direct connection

### Resource Monitoring

```bash
# Container resource usage
docker stats

# Disk usage
docker system df

# Network usage
docker network ls
```

## 🚀 Scaling

### Horizontal Scaling

Scale the application service:

```bash
# Scale to 3 instances
docker-compose -f docker/docker-compose.yml up -d --scale adverse-news-screening=3

# Use load balancer (nginx example)
# Add nginx service to docker/docker-compose.yml
```

### Performance Tuning

1. **Adjust resource limits** in production compose file
2. **Optimize MongoDB** with appropriate indexes
3. **Configure connection pooling** for high load
4. **Enable application caching** if needed

## 📝 Maintenance

### Regular Tasks

```bash
# Update images
docker-compose -f docker/docker-compose.yml pull
docker-compose -f docker/docker-compose.yml up -d

# Clean up unused resources
docker system prune -a

# Backup configuration
tar -czf backup-$(date +%Y%m%d).tar.gz .env docker/docker-compose*.yml config/
```

### Updates

```bash
# Pull latest code
git pull

# Rebuild and restart
./scripts/docker.sh stop
./scripts/docker.sh build
./scripts/docker.sh start
```

## 📦 Building and Publishing Docker Images

### Build Docker Image

To create a Docker image for your Adverse News Screening application:

```bash
# Build the image with a specific tag
docker build -f docker/Dockerfile -t adverse-news-screening:latest .

# Build with version tag
docker build -f docker/Dockerfile -t adverse-news-screening:v1.0.0 .

# Build with custom registry prefix
docker build -f docker/Dockerfile -t your-registry.com/adverse-news-screening:latest .
```

### Tag Images for Remote Repository

Before uploading to a remote repository, tag your image appropriately:

```bash
# For Docker Hub
docker tag adverse-news-screening:latest your-dockerhub-username/adverse-news-screening:latest
docker tag adverse-news-screening:latest your-dockerhub-username/adverse-news-screening:v1.0.0

# For GitHub Container Registry
docker tag adverse-news-screening:latest ghcr.io/your-username/adverse-news-screening:latest
docker tag adverse-news-screening:latest ghcr.io/your-username/adverse-news-screening:v1.0.0

# For AWS ECR
docker tag adverse-news-screening:latest 123456789012.dkr.ecr.us-west-2.amazonaws.com/adverse-news-screening:latest

# For Google Container Registry
docker tag adverse-news-screening:latest gcr.io/your-project-id/adverse-news-screening:latest

# For Azure Container Registry
docker tag adverse-news-screening:latest your-registry.azurecr.io/adverse-news-screening:latest
```

### Upload to Remote Repositories

#### Docker Hub

1. **Login to Docker Hub**:
```bash
docker login
# Enter your Docker Hub username and password
```

2. **Push the image**:
```bash
docker push your-dockerhub-username/adverse-news-screening:latest
docker push your-dockerhub-username/adverse-news-screening:v1.0.0
```

#### GitHub Container Registry (GHCR)

1. **Create a Personal Access Token** with `write:packages` permission in GitHub settings

2. **Login to GHCR**:
```bash
echo $GITHUB_TOKEN | docker login ghcr.io -u your-username --password-stdin
# Or interactively:
docker login ghcr.io -u your-username
```

3. **Push the image**:
```bash
docker push ghcr.io/your-username/adverse-news-screening:latest
docker push ghcr.io/your-username/adverse-news-screening:v1.0.0
```

#### AWS Elastic Container Registry (ECR)

1. **Install and configure AWS CLI**:
```bash
aws configure
```

2. **Get login token**:
```bash
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin 123456789012.dkr.ecr.us-west-2.amazonaws.com
```

3. **Create repository** (if it doesn't exist):
```bash
aws ecr create-repository --repository-name adverse-news-screening --region us-west-2
```

4. **Push the image**:
```bash
docker push 123456789012.dkr.ecr.us-west-2.amazonaws.com/adverse-news-screening:latest
```

#### Google Container Registry (GCR)

1. **Install and configure gcloud CLI**:
```bash
gcloud auth configure-docker
```

2. **Push the image**:
```bash
docker push gcr.io/your-project-id/adverse-news-screening:latest
```

#### Azure Container Registry (ACR)

1. **Login to Azure**:
```bash
az login
az acr login --name your-registry
```

2. **Push the image**:
```bash
docker push your-registry.azurecr.io/adverse-news-screening:latest
```

### Automated Build and Push Script

Create a script to automate the build and push process:

```bash
#!/bin/bash
# build-and-push.sh

set -e

# Configuration
REGISTRY="your-dockerhub-username"  # Change this to your registry
IMAGE_NAME="adverse-news-screening"
VERSION=${1:-latest}

echo "🔨 Building Docker image..."
docker build -f docker/Dockerfile -t ${IMAGE_NAME}:${VERSION} .

echo "🏷️  Tagging image for registry..."
docker tag ${IMAGE_NAME}:${VERSION} ${REGISTRY}/${IMAGE_NAME}:${VERSION}

if [ "$VERSION" != "latest" ]; then
    docker tag ${IMAGE_NAME}:${VERSION} ${REGISTRY}/${IMAGE_NAME}:latest
fi

echo "📤 Pushing to registry..."
docker push ${REGISTRY}/${IMAGE_NAME}:${VERSION}

if [ "$VERSION" != "latest" ]; then
    docker push ${REGISTRY}/${IMAGE_NAME}:latest
fi

echo "✅ Successfully pushed ${REGISTRY}/${IMAGE_NAME}:${VERSION}"
```

Make it executable and use it:
```bash
chmod +x scripts/build-and-push.sh

# Push with latest tag
./scripts/build-and-push.sh

# Push with specific version
./scripts/build-and-push.sh v1.0.0
```

### Using Published Images

Once your image is published, others can use it:

```bash
# Pull and run from Docker Hub
docker run -d -p 8280:8280 --name adverse-news-screening your-dockerhub-username/adverse-news-screening:latest

# Pull and run from GHCR
docker run -d -p 8280:8280 --name adverse-news-screening ghcr.io/your-username/adverse-news-screening:latest

# Use in docker-compose.yml
version: '3.8'
services:
  adverse-news-screening:
    image: your-dockerhub-username/adverse-news-screening:latest
    # ... rest of configuration
```

### Multi-Platform Builds

For compatibility across different architectures (ARM64, AMD64):

```bash
# Create and use a new builder
docker buildx create --name multiarch --use

# Build for multiple platforms
docker buildx build -f docker/Dockerfile --platform linux/amd64,linux/arm64 \
  -t your-registry/adverse-news-screening:latest \
  --push .
```

### Best Practices for Image Publishing

1. **Use semantic versioning** for tags (v1.0.0, v1.1.0, etc.)
2. **Always tag with 'latest'** for the most recent stable version
3. **Include build metadata** in image labels:
```dockerfile
LABEL version="1.0.0" \
      description="Adverse News Screening Application" \
      maintainer="your-email@example.com" \
      build-date="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
```
4. **Keep images small** by using multi-stage builds and minimal base images
5. **Scan for vulnerabilities** before publishing:
```bash
docker scout cves adverse-news-screening:latest
```
