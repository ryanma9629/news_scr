#!/bin/bash

# Adverse News Screening Docker Build Script

set -e

echo "🐳 Building Adverse News Screening Docker Image..."

# Navigate to project root
cd "$(dirname "$0")/.."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env file with your actual API keys and configuration before running the application."
fi

# Build the Docker image
echo "🔨 Building Docker image..."
docker-compose -f docker/docker-compose.yml build

echo "✅ Build completed successfully!"
echo ""
echo "To start the application:"
echo "  docker-compose -f docker/docker-compose.yml up -d"
echo ""
echo "To view logs:"
echo "  docker-compose -f docker/docker-compose.yml logs -f"
echo ""
echo "To stop the application:"
echo "  docker-compose -f docker/docker-compose.yml down"
