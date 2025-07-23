# News Scraper - Docker Deployment Guide

This guide provides comprehensive instructions for deploying the News Scraper application using Docker.

## 📋 Prerequisites

- Docker Engine (version 20.10 or higher)
- Docker Compose (version 2.0 or higher)
- At least 4GB of available RAM
- Azure OpenAI API access (required)

## 🚀 Quick Start

### 1. Clone and Setup

```bash
# Navigate to the project directory
cd /home/sas/work/news_scr

# Make management scripts executable
chmod +x docker.sh build.sh

# Use the management script for easy deployment
./docker.sh build
./docker.sh start
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
- `AZURE_OPENAI_API_VERSION`: API version (default: 2024-02-01)

### 3. Access Application

- **Web Interface**: http://localhost:8280
- **API Health Check**: http://localhost:8280/api/health
- **MongoDB**: localhost:27017

## 📁 Docker Files Overview

| File | Purpose |
|------|---------|
| `Dockerfile` | Main application container definition |
| `docker-compose.yml` | Development deployment configuration |
| `docker-compose.prod.yml` | Production deployment configuration |
| `.dockerignore` | Files excluded from Docker build context |
| `docker.sh` | Management script for common operations |
| `build.sh` | Simple build script |
| `.env.example` | Environment variables template |

## 🛠 Management Commands

Use the `docker.sh` script for easy management:

```bash
# Build the application
./docker.sh build

# Start services
./docker.sh start

# Stop services
./docker.sh stop

# Restart services
./docker.sh restart

# View logs (all services)
./docker.sh logs

# View logs (specific service)
./docker.sh logs news-scraper
./docker.sh logs mongodb

# Check status
./docker.sh status

# Clean up (removes all data!)
./docker.sh clean
```

## 🔧 Manual Docker Commands

If you prefer manual control:

```bash
# Build and start
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Rebuild specific service
docker-compose build news-scraper

# Access service shell
docker-compose exec news-scraper bash
docker-compose exec mongodb mongosh
```

## 🏭 Production Deployment

For production environments, use the production configuration:

```bash
# Use production compose file
docker-compose -f docker-compose.prod.yml up -d

# Or with override
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
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
python generate_ssl.py
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

1. **Uncomment authentication variables** in `docker-compose.prod.yml`:
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

## 🗃 Data Management

### Database Persistence

MongoDB data is stored in Docker volumes:
- `mongodb_data`: Database files
- `mongodb_config`: Configuration files

### Backup and Restore

```bash
# Backup database
docker-compose exec mongodb mongodump --out /tmp/backup
docker cp $(docker-compose ps -q mongodb):/tmp/backup ./backup

# Restore database
docker cp ./backup $(docker-compose ps -q mongodb):/tmp/backup
docker-compose exec mongodb mongorestore /tmp/backup
```

## 🐛 Troubleshooting

### Common Issues

1. **Port already in use**:
```bash
# Check what's using the port
sudo lsof -i :8280
sudo lsof -i :27017

# Change port in docker-compose.yml or stop conflicting service
```

2. **MongoDB connection issues**:
```bash
# Check MongoDB logs
./docker.sh logs mongodb

# Verify MongoDB health
docker-compose exec mongodb mongosh --eval "db.adminCommand('ping')"
```

3. **Application won't start**:
```bash
# Check application logs
./docker.sh logs news-scraper

# Verify environment variables
docker-compose exec news-scraper env | grep -E "(AZURE|MONGO)"
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
docker-compose ps

# Manual health check
curl http://localhost:8280/api/health
```

### Log Analysis

```bash
# Follow all logs
docker-compose logs -f

# Filter by service
docker-compose logs -f news-scraper | grep ERROR

# Check MongoDB operations
docker-compose logs mongodb | grep -E "(connection|error)"
```

## 🔧 Development

### Development Mode

Enable development features:

```bash
# Set in .env file
RELOAD=true

# Or override in docker-compose
docker-compose run --rm -p 8280:8280 -e RELOAD=true news-scraper
```

### Code Changes

For development with live reload:

```bash
# Mount source code
docker-compose run --rm -p 8280:8280 -v $(pwd):/app news-scraper python serv_fastapi.py
```

### Debugging

```bash
# Access application container
docker-compose exec news-scraper bash

# Check Python environment
docker-compose exec news-scraper python -c "import sys; print(sys.path)"

# Test database connection
docker-compose exec news-scraper python -c "from docstore import MongoStore; store = MongoStore('test', 'en'); print('Connection OK')"
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
docker-compose up -d --scale news-scraper=3

# Use load balancer (nginx example)
# Add nginx service to docker-compose.yml
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
docker-compose pull
docker-compose up -d

# Clean up unused resources
docker system prune -a

# Backup configuration
tar -czf backup-$(date +%Y%m%d).tar.gz .env docker-compose*.yml mongo-init/
```

### Updates

```bash
# Pull latest code
git pull

# Rebuild and restart
./docker.sh stop
./docker.sh build
./docker.sh start
```

## 📞 Support

For issues with the Docker deployment:

1. Check the troubleshooting section above
2. Review application and MongoDB logs
3. Verify environment configuration
4. Test individual components

Remember to never commit sensitive information like API keys to version control!
