#!/bin/bash

# News Scraper Docker Build Script

set -e

echo "🐳 Building News Scraper Docker Image..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Copying from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env file with your actual API keys and configuration before running the application."
fi

# Build the Docker image
echo "🔨 Building Docker image..."
docker-compose build

echo "✅ Build completed successfully!"
echo ""
echo "To start the application:"
echo "  docker-compose up -d"
echo ""
echo "To view logs:"
echo "  docker-compose logs -f"
echo ""
echo "To stop the application:"
echo "  docker-compose down"
