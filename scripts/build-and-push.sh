#!/bin/bash

# Adverse News Screening - Build and Push Script
# Automates building and pushing Docker images to remote repositories

set -e

# Navigate to project root
cd "$(dirname "$0")/.."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

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

# Configuration - Modify these according to your setup
DEFAULT_REGISTRY="your-dockerhub-username"  # Change this!
IMAGE_NAME="adverse-news-screening"
DOCKERFILE="docker/Dockerfile"

# Parse command line arguments
REGISTRY=${REGISTRY:-$DEFAULT_REGISTRY}
VERSION=${1:-latest}
PUSH=${PUSH:-true}
PLATFORMS=${PLATFORMS:-"linux/amd64"}

show_help() {
    echo "Adverse News Screening Docker Build and Push Script"
    echo ""
    echo "Usage: $0 [VERSION] [OPTIONS]"
    echo ""
    echo "Arguments:"
    echo "  VERSION    Image version tag (default: latest)"
    echo ""
    echo "Environment Variables:"
    echo "  REGISTRY   Docker registry (default: $DEFAULT_REGISTRY)"
    echo "  PUSH       Push to registry (default: true, set to false to build only)"
    echo "  PLATFORMS  Target platforms (default: linux/amd64)"
    echo ""
    echo "Examples:"
    echo "  $0                           # Build and push with 'latest' tag"
    echo "  $0 v1.0.0                    # Build and push with 'v1.0.0' tag"
    echo "  REGISTRY=ghcr.io/user $0     # Use GitHub Container Registry"
    echo "  PUSH=false $0                # Build only, don't push"
    echo ""
    echo "Supported registries:"
    echo "  - Docker Hub: your-username"
    echo "  - GitHub: ghcr.io/your-username"
    echo "  - AWS ECR: 123456789012.dkr.ecr.region.amazonaws.com"
    echo "  - Google GCR: gcr.io/project-id"
    echo "  - Azure ACR: registry.azurecr.io"
}

# Check if help is requested
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    show_help
    exit 0
fi

# Validate configuration
if [[ "$REGISTRY" == "your-dockerhub-username" ]]; then
    print_error "Please set your registry name!"
    print_info "Either modify the script or set REGISTRY environment variable:"
    print_info "  export REGISTRY=your-dockerhub-username"
    print_info "  export REGISTRY=ghcr.io/your-username"
    exit 1
fi

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed or not in PATH"
    exit 1
fi

print_info "Starting build process..."
print_info "Registry: $REGISTRY"
print_info "Image: $IMAGE_NAME"
print_info "Version: $VERSION"
print_info "Platforms: $PLATFORMS"
print_info "Push: $PUSH"

# Build the image
print_info "🔨 Building Docker image..."

# Check if we should use buildx for multi-platform builds
if [[ "$PLATFORMS" == *","* ]] || [[ "$PLATFORMS" == *"arm"* ]]; then
    print_info "Using buildx for multi-platform build..."
    
    # Ensure buildx is available
    if ! docker buildx version &> /dev/null; then
        print_error "Docker buildx is not available"
        exit 1
    fi
    
    # Create builder if it doesn't exist
    if ! docker buildx inspect multiarch &> /dev/null; then
        print_info "Creating multiarch builder..."
        docker buildx create --name multiarch --use
    else
        docker buildx use multiarch
    fi
    
    # Build arguments
    BUILD_ARGS="--platform $PLATFORMS"
    if [[ "$PUSH" == "true" ]]; then
        BUILD_ARGS="$BUILD_ARGS --push"
    else
        BUILD_ARGS="$BUILD_ARGS --load"
    fi
    
    docker buildx build $BUILD_ARGS \
        -t ${REGISTRY}/${IMAGE_NAME}:${VERSION} \
        -f ${DOCKERFILE} .
        
    if [ "$VERSION" != "latest" ] && [[ "$PUSH" == "true" ]]; then
        print_info "🏷️  Tagging as latest..."
        docker buildx build $BUILD_ARGS \
            -t ${REGISTRY}/${IMAGE_NAME}:latest \
            -f ${DOCKERFILE} .
    fi
else
    # Regular build
    docker build -t ${IMAGE_NAME}:${VERSION} -f ${DOCKERFILE} .
    
    print_info "🏷️  Tagging for registry..."
    docker tag ${IMAGE_NAME}:${VERSION} ${REGISTRY}/${IMAGE_NAME}:${VERSION}
    
    if [ "$VERSION" != "latest" ]; then
        docker tag ${IMAGE_NAME}:${VERSION} ${REGISTRY}/${IMAGE_NAME}:latest
    fi
    
    # Push if requested
    if [[ "$PUSH" == "true" ]]; then
        print_info "📤 Pushing to registry..."
        docker push ${REGISTRY}/${IMAGE_NAME}:${VERSION}
        
        if [ "$VERSION" != "latest" ]; then
            print_info "📤 Pushing latest tag..."
            docker push ${REGISTRY}/${IMAGE_NAME}:latest
        fi
    fi
fi

if [[ "$PUSH" == "true" ]]; then
    print_success "Successfully pushed ${REGISTRY}/${IMAGE_NAME}:${VERSION}"
    print_info "You can now use the image with:"
    print_info "  docker run -d -p 8280:8280 ${REGISTRY}/${IMAGE_NAME}:${VERSION}"
else
    print_success "Successfully built ${REGISTRY}/${IMAGE_NAME}:${VERSION}"
    print_info "To push the image, run:"
    print_info "  PUSH=true $0 $VERSION"
fi

print_info "Available local images:"
docker images ${REGISTRY}/${IMAGE_NAME} --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
