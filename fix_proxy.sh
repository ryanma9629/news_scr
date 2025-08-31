#!/bin/bash

# Script to fix proxy settings for Crawl4AI localhost connections

echo "🔧 Fixing proxy settings for Crawl4AI..."

# Check current proxy settings
echo "Current proxy environment variables:"
env | grep -i proxy

echo ""
echo "Adding localhost to NO_PROXY settings..."

# Export NO_PROXY settings for localhost
export NO_PROXY="localhost,127.0.0.1,::1,${NO_PROXY}"
export no_proxy="localhost,127.0.0.1,::1,${no_proxy}"

echo "Updated NO_PROXY: $NO_PROXY"
echo "Updated no_proxy: $no_proxy"

echo ""
echo "✅ Proxy settings updated for current session"
echo ""
echo "To make this permanent, add these lines to your ~/.bashrc or ~/.zshrc:"
echo "export NO_PROXY=\"localhost,127.0.0.1,::1,\${NO_PROXY}\""
echo "export no_proxy=\"localhost,127.0.0.1,::1,\${no_proxy}\""

# Test the connection
echo ""
echo "Testing Crawl4AI connection..."
python3 test_crawl4ai_proxy.py
