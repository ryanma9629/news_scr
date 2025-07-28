#!/bin/bash

# Adverse News Screening Docker Management Script

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
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

# Check if Docker and Docker Compose are installed
check_dependencies() {
    print_info "Checking dependencies..."
    
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed. Please install Docker first."
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        print_error "Docker Compose is not installed. Please install Docker Compose first."
        exit 1
    fi
    
    print_success "Dependencies check passed"
}

# Setup environment file
setup_env() {
    if [ ! -f .env ]; then
        print_warning ".env file not found. Creating from template..."
        cp .env.example .env
        print_info "Please edit .env file with your actual API keys before starting the application."
        print_info "Required: AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, DEEPSEEK_API_KEY, DASHSCOPE_API_KEY"
        return 1
    fi
    return 0
}

# Build the application
build() {
    print_info "Building Adverse News Screening Docker image..."
    docker-compose build
    print_success "Build completed successfully!"
}

# Start the application
start() {
    print_info "Starting Adverse News Screening application..."
    docker-compose up -d
    
    print_success "Application started successfully!"
    print_info "Access the application at: http://localhost:8280"
    print_info "MongoDB is available at: localhost:27017"
}

# Stop the application
stop() {
    print_info "Stopping Adverse News Screening application..."
    docker-compose down
    print_success "Application stopped successfully!"
}

# Show logs
logs() {
    if [ "$1" ]; then
        docker-compose logs -f "$1"
    else
        docker-compose logs -f
    fi
}

# Show status
status() {
    print_info "Application status:"
    docker-compose ps
}

# Clean up (remove containers and volumes)
clean() {
    print_warning "This will remove all containers and volumes (including database data)!"
    read -p "Are you sure? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Cleaning up..."
        docker-compose down -v --remove-orphans
        docker system prune -f
        print_success "Cleanup completed!"
    else
        print_info "Cleanup cancelled"
    fi
}

# Show help
show_help() {
    echo "Adverse News Screening Docker Management Script"
    echo ""
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  build    Build the Docker image"
    echo "  start    Start the application"
    echo "  stop     Stop the application"
    echo "  restart  Restart the application"
    echo "  logs     Show application logs (optional: specify service name)"
    echo "  status   Show application status"
    echo "  clean    Remove all containers and volumes"
    echo "  help     Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0 build"
    echo "  $0 start"
    echo "  $0 logs news-scraper"
    echo "  $0 status"
}

# Main script logic
main() {
    case "${1:-help}" in
        "build")
            check_dependencies
            if setup_env; then
                build
            else
                print_error "Please configure .env file first"
                exit 1
            fi
            ;;
        "start")
            check_dependencies
            if setup_env; then
                start
            else
                print_error "Please configure .env file first"
                exit 1
            fi
            ;;
        "stop")
            check_dependencies
            stop
            ;;
        "restart")
            check_dependencies
            stop
            if setup_env; then
                start
            else
                print_error "Please configure .env file first"
                exit 1
            fi
            ;;
        "logs")
            check_dependencies
            logs "$2"
            ;;
        "status")
            check_dependencies
            status
            ;;
        "clean")
            check_dependencies
            clean
            ;;
        "help"|*)
            show_help
            ;;
    esac
}

main "$@"
