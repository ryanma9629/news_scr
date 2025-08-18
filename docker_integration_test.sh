#!/bin/bash

# Docker Integration Test for PostgreSQL and MongoDB services
# This script tests if the services can start up properly

set -e

echo "🐳 Starting Docker Integration Test for Adverse News Screening App..."

# Navigate to docker directory
cd "$(dirname "$0")/docker"

echo "📋 Validating Docker Compose configuration..."
docker-compose config >/dev/null
echo "✅ Docker Compose configuration is valid"

echo "🚀 Starting services in background..."
docker-compose up -d

echo "⏳ Waiting for services to be healthy..."
sleep 30

echo "🔍 Checking service status..."

# Check if containers are running
if docker-compose ps | grep -q "Up"; then
    echo "✅ Services are running"
else
    echo "❌ Some services failed to start"
    docker-compose logs
    exit 1
fi

# Check PostgreSQL health
if docker-compose exec -T postgres pg_isready -U postgres > /dev/null 2>&1; then
    echo "✅ PostgreSQL is healthy"
else
    echo "❌ PostgreSQL health check failed"
    docker-compose logs postgres
    exit 1
fi

# Check MongoDB health
if docker-compose exec -T mongodb mongosh --eval "db.adminCommand('ping')" > /dev/null 2>&1; then
    echo "✅ MongoDB is healthy"
else
    echo "❌ MongoDB health check failed"
    docker-compose logs mongodb
    exit 1
fi

# Test database initialization
echo "🗄️ Testing database initialization..."

# Check if PostgreSQL table was created
if docker-compose exec -T postgres psql -U postgres -d adverse_news_screening -c "\dt" | grep -q "fc_tags"; then
    echo "✅ PostgreSQL fc_tags table exists"
else
    echo "❌ PostgreSQL fc_tags table was not created"
    exit 1
fi

echo "🧹 Cleaning up..."
docker-compose down

echo "🎉 All integration tests passed! The PostgreSQL integration is ready for production."
