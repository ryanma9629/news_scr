#!/usr/bin/env python3
"""
Debug script to test the complete customer_id flow from URL to PostgreSQL.
"""

import asyncio
import json
import requests
from urllib.parse import urlencode

# Test configuration
BASE_URL = "https://sasserver.demo.sas.com:8280"
TEST_COMPANY = "Theranos"
TEST_CUSTOMER_ID = "1324579"

async def test_customer_id_flow():
    """Test the complete customer_id flow."""
    
    print("=== Testing Customer ID Flow ===")
    print(f"Base URL: {BASE_URL}")
    print(f"Test Company: {TEST_COMPANY}")
    print(f"Test Customer ID: {TEST_CUSTOMER_ID}")
    print()
    
    # Step 1: Test the root endpoint with URL parameters
    print("Step 1: Testing root endpoint with URL parameters...")
    params = {"company_name": TEST_COMPANY, "customer_id": TEST_CUSTOMER_ID}
    root_url = f"{BASE_URL}/?{urlencode(params)}"
    print(f"URL: {root_url}")
    
    try:
        response = requests.get(root_url, verify=False, timeout=10)
        print(f"Status: {response.status_code}")
        
        # Check if the JavaScript variables are in the HTML
        html_content = response.text
        if f'window.URL_CUSTOMER_ID = "{TEST_CUSTOMER_ID}"' in html_content:
            print("✓ Customer ID correctly injected into HTML")
        else:
            print("✗ Customer ID NOT found in HTML")
            # Print relevant part of HTML for debugging
            if "window.URL_CUSTOMER_ID" in html_content:
                start = html_content.find("window.URL_CUSTOMER_ID")
                end = html_content.find("\n", start)
                print(f"Found: {html_content[start:end]}")
        
        if 'window.VI_DEPLOY = true' in html_content:
            print("✓ VI_DEPLOY correctly set to true in HTML")
        else:
            print("✗ VI_DEPLOY NOT set to true in HTML")
            if "window.VI_DEPLOY" in html_content:
                start = html_content.find("window.VI_DEPLOY")
                end = html_content.find("\n", start)
                print(f"Found: {html_content[start:end]}")
                
    except Exception as e:
        print(f"✗ Error testing root endpoint: {e}")
    
    print()
    
    # Step 2: Test a direct API call with customer_id
    print("Step 2: Testing direct API call with customer_id...")
    api_url = f"{BASE_URL}/api/tagging"
    
    # Simulate what the frontend would send
    api_data = {
        "urls": ["https://example.com/test"],
        "company_name": TEST_COMPANY,
        "customer_id": TEST_CUSTOMER_ID,
        "lang": "en-US",
        "tagging_method": "rag",
        "llm_model": "gpt-4o",
        "tags_save": True,
        "tags_load": False,
        "tags_save_days": 90,
        "tags_load_days": 90,
        "session_id": "test_session"
    }
    
    print(f"API URL: {api_url}")
    print(f"Sending customer_id: '{TEST_CUSTOMER_ID}'")
    
    try:
        response = requests.post(
            api_url, 
            json=api_data, 
            verify=False, 
            timeout=30,
            headers={"Content-Type": "application/json"}
        )
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print("✓ API call successful")
            print(f"Response: {json.dumps(result, indent=2)}")
        else:
            print("✗ API call failed")
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"✗ Error testing API endpoint: {e}")

if __name__ == "__main__":
    asyncio.run(test_customer_id_flow())
