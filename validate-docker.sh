#!/bin/bash

# Docker Setup Validation Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${BLUE}🔍 $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

echo "🐳 News Scraper Docker Setup Validation"
echo "========================================"

# Check if Docker is running
print_step "Checking Docker daemon..."
if docker info >/dev/null 2>&1; then
    print_success "Docker daemon is running"
else
    print_error "Docker daemon is not running"
    exit 1
fi

# Check if Docker Compose is available
print_step "Checking Docker Compose..."
if docker-compose --version >/dev/null 2>&1; then
    print_success "Docker Compose is available"
else
    print_error "Docker Compose is not available"
    exit 1
fi

# Check if required files exist
print_step "Checking required files..."
required_files=(
    "Dockerfile"
    "docker-compose.yml"
    "requirements.txt"
    "serv_fastapi.py"
    ".env.example"
)

for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        print_success "Found $file"
    else
        print_error "Missing $file"
        exit 1
    fi
done

# Check if .env file exists
print_step "Checking environment configuration..."
if [ -f ".env" ]; then
    print_success "Found .env file"
    
    # Check for required environment variables
    required_vars=("AZURE_OPENAI_API_KEY" "AZURE_OPENAI_ENDPOINT")
    for var in "${required_vars[@]}"; do
        if grep -q "^${var}=" .env && ! grep -q "^${var}=.*_here" .env; then
            print_success "$var is configured"
        else
            print_warning "$var needs to be configured in .env file"
        fi
    done
else
    print_warning ".env file not found - will be created from template"
fi

# Check if ports are available
print_step "Checking port availability..."
if ! lsof -i :8280 >/dev/null 2>&1; then
    print_success "Port 8280 is available"
else
    print_warning "Port 8280 is in use - application may conflict"
fi

if ! lsof -i :27017 >/dev/null 2>&1; then
    print_success "Port 27017 is available"
else
    print_warning "Port 27017 is in use - MongoDB may conflict"
fi

# Validate Docker Compose syntax
print_step "Validating Docker Compose configuration..."
if docker-compose config >/dev/null 2>&1; then
    print_success "Docker Compose configuration is valid"
else
    print_error "Docker Compose configuration has errors"
    docker-compose config
    exit 1
fi

# Check if images can be built
print_step "Testing Docker build..."
if docker-compose build --dry-run >/dev/null 2>&1; then
    print_success "Docker build configuration is valid"
else
    print_warning "Docker build may have issues - run 'docker-compose build' to test"
fi

# Test if services can start (dry run)
print_step "Testing service configuration..."
if docker-compose up --dry-run >/dev/null 2>&1; then
    print_success "Service configuration is valid"
else
    print_warning "Service configuration may have issues"
fi

# Check SSL certificates if they exist
print_step "Checking SSL certificates..."
if [ -f "cert.pem" ] && [ -f "key.pem" ]; then
    print_success "SSL certificates found"
    
    # Validate certificate
    if openssl x509 -in cert.pem -text -noout >/dev/null 2>&1; then
        print_success "SSL certificate is valid"
    else
        print_warning "SSL certificate may be invalid"
    fi
else
    print_warning "SSL certificates not found - HTTPS will not be available"
    print_warning "Run 'python generate_ssl.py' to create self-signed certificates"
fi

echo ""
echo "🎉 Validation Complete!"
echo ""
echo "Next steps:"
echo "1. Configure .env file with your API keys"
echo "2. Run './docker.sh build' to build the application"
echo "3. Run './docker.sh start' to start the services"
echo "4. Access the application at http://localhost:8280"
echo ""
print_warning "Remember: Azure OpenAI API key is required for the application to work!"
