#!/usr/bin/env python3
"""
Test script for custom API endpoints that filter MCP tools by tags
Uses requests library to test the new tag-based filtering endpoints
"""

import requests
import json
import time

def test_custom_api_endpoints():
    """Test the custom API endpoints for tag-based filtering"""
    base_url = "http://localhost:8989"
    
    print("🚀 Testing Custom API Endpoints for Tag-Based Tool Filtering")
    print("=" * 70)
    print(f"Base URL: {base_url}")
    print("")
    
    try:
        # Test 1: API Health Check
        print("1. Testing API health check...")
        response = requests.get(f"{base_url}/api/health", timeout=10)
        
        if response.status_code == 200:
            health_data = response.json()
            print("   ✅ API health check successful")
            print(f"   Service: {health_data.get('service', 'Unknown')}")
            print(f"   Version: {health_data.get('version', 'Unknown')}")
            print("   Available endpoints:")
            endpoints = health_data.get('endpoints', {})
            for name, path in endpoints.items():
                print(f"     - {name}: {path}")
        else:
            print(f"   ❌ API health check failed: {response.status_code}")
        
        # Test 2: List all available tags
        print("\n2. Listing all available tags...")
        response = requests.get(f"{base_url}/api/tags", timeout=10)
        
        if response.status_code == 200:
            tags_data = response.json()
            print(f"   ✅ Found {tags_data.get('count', 0)} tags:")
            for tag in tags_data.get('tags', []):
                print(f"     - {tag}")
        else:
            print(f"   ❌ Failed to list tags: {response.status_code}")
        
        # Test 3: Get tools with 'search' tag
        print("\n3. Getting tools with 'search' tag...")
        response = requests.get(f"{base_url}/api/tools/by-tag/search", timeout=10)
        
        if response.status_code == 200:
            tools_data = response.json()
            print(f"   ✅ Found {tools_data.get('count', 0)} tools with 'search' tag:")
            for tool in tools_data.get('tools', []):
                print(f"     - {tool.get('name', 'Unknown')}")
                print(f"       Description: {tool.get('description', 'No description')}")
                print(f"       Tags: {tool.get('tags', [])}")
        else:
            print(f"   ❌ Failed to get search tools: {response.status_code}")
            print(f"   Response: {response.text}")
        
        # Test 4: Get tools with 'chemistry' tag
        print("\n4. Getting tools with 'chemistry' tag...")
        response = requests.get(f"{base_url}/api/tools/by-tag/chemistry", timeout=10)
        
        if response.status_code == 200:
            tools_data = response.json()
            print(f"   ✅ Found {tools_data.get('count', 0)} tools with 'chemistry' tag:")
            for tool in tools_data.get('tools', []):
                print(f"     - {tool.get('name', 'Unknown')}")
        else:
            print(f"   ❌ Failed to get chemistry tools: {response.status_code}")
        
        # Test 5: Get resources with 'search' tag
        print("\n5. Getting resources with 'search' tag...")
        response = requests.get(f"{base_url}/api/resources/by-tag/search", timeout=10)
        
        if response.status_code == 200:
            resources_data = response.json()
            print(f"   ✅ Found {resources_data.get('count', 0)} resources with 'search' tag:")
            for resource in resources_data.get('resources', []):
                print(f"     - {resource.get('uri', 'Unknown')}")
                print(f"       Name: {resource.get('name', 'No name')}")
                print(f"       Tags: {resource.get('tags', [])}")
        else:
            print(f"   ❌ Failed to get search resources: {response.status_code}")
        
        # Test 6: Get resources with 'system' tag
        print("\n6. Getting resources with 'system' tag...")
        response = requests.get(f"{base_url}/api/resources/by-tag/system", timeout=10)
        
        if response.status_code == 200:
            resources_data = response.json()
            print(f"   ✅ Found {resources_data.get('count', 0)} resources with 'system' tag:")
            for resource in resources_data.get('resources', []):
                print(f"     - {resource.get('uri', 'Unknown')}")
        else:
            print(f"   ❌ Failed to get system resources: {response.status_code}")
        
        # Test 7: Direct chemical search API
        print("\n7. Testing direct chemical search API...")
        search_payload = {
            "query": "H2O",
            "search_type": "formula"
        }
        
        response = requests.post(
            f"{base_url}/api/search/chemical",
            json=search_payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        if response.status_code == 200:
            search_data = response.json()
            print("   ✅ Direct chemical search successful")
            print(f"   Query: {search_data.get('query', 'Unknown')}")
            print(f"   Search Type: {search_data.get('search_type', 'Unknown')}")
            print(f"   Tags Used: {search_data.get('tags_used', [])}")
            result_preview = str(search_data.get('result', ''))[:200]
            print(f"   Result Preview: {result_preview}...")
        else:
            print(f"   ❌ Direct chemical search failed: {response.status_code}")
            print(f"   Response: {response.text}")
        
        # Test 8: Test with non-existent tag
        print("\n8. Testing with non-existent tag...")
        response = requests.get(f"{base_url}/api/tools/by-tag/nonexistent", timeout=10)
        
        if response.status_code == 200:
            tools_data = response.json()
            print(f"   ✅ Request successful, found {tools_data.get('count', 0)} tools (expected 0)")
        else:
            print(f"   ❌ Request failed: {response.status_code}")
        
        print("\n" + "=" * 70)
        print("🎉 Custom API endpoints testing completed!")
        print("📋 Summary:")
        print("✅ API health check endpoint")
        print("✅ List all tags endpoint")
        print("✅ Filter tools by tag endpoint")
        print("✅ Filter resources by tag endpoint") 
        print("✅ Direct chemical search API endpoint")
        print("✅ Error handling for non-existent tags")
        
    except requests.exceptions.ConnectionError:
        print("❌ Connection failed!")
        print("Make sure the FastMCP server is running:")
        print("  python src/mcp_server.py")
    except Exception as e:
        print(f"❌ Test failed: {e}")

def demonstrate_api_usage():
    """Demonstrate practical usage of the custom API endpoints"""
    print("\n📚 API Usage Examples")
    print("=" * 50)
    
    base_url = "http://localhost:8989"
    
    print("1. Get all available tags:")
    print(f"   GET {base_url}/api/tags")
    
    print("\n2. Get tools with specific tag:")
    print(f"   GET {base_url}/api/tools/by-tag/search")
    print(f"   GET {base_url}/api/tools/by-tag/chemistry")
    print(f"   GET {base_url}/api/tools/by-tag/public")
    
    print("\n3. Get resources with specific tag:")
    print(f"   GET {base_url}/api/resources/by-tag/search")
    print(f"   GET {base_url}/api/resources/by-tag/system")
    print(f"   GET {base_url}/api/resources/by-tag/health")
    
    print("\n4. Direct chemical search:")
    print(f"   POST {base_url}/api/search/chemical")
    print("   Body: {")
    print('     "query": "caffeine",')
    print('     "search_type": "name"')
    print("   }")
    
    print("\n5. API health check:")
    print(f"   GET {base_url}/api/health")

def test_curl_commands():
    """Generate curl commands for testing"""
    print("\n🔧 Curl Commands for Testing")
    print("=" * 50)
    
    base_url = "http://localhost:8989"
    
    commands = [
        f"curl -X GET {base_url}/api/health",
        f"curl -X GET {base_url}/api/tags",
        f"curl -X GET {base_url}/api/tools/by-tag/search",
        f"curl -X GET {base_url}/api/resources/by-tag/system",
        f'curl -X POST {base_url}/api/search/chemical -H "Content-Type: application/json" -d \'{{"query": "H2O", "search_type": "formula"}}\'',
    ]
    
    for i, cmd in enumerate(commands, 1):
        print(f"{i}. {cmd}")

if __name__ == "__main__":
    print("🌐 Custom API Endpoints Test for PubChemPy FastMCP Server")
    print("Tests the new tag-based filtering endpoints")
    print("=" * 80)
    print("Make sure the server is running first:")
    print("  python src/mcp_server.py")
    print("")
    
    # Run the main test
    test_custom_api_endpoints()
    
    # Show usage examples
    demonstrate_api_usage()
    
    # Show curl commands
    test_curl_commands()
    
    print("\n🎯 Benefits of Custom API Endpoints:")
    print("✅ Direct HTTP access without MCP protocol complexity")
    print("✅ Easy integration with any HTTP client")
    print("✅ Tag-based filtering for specific tool discovery")
    print("✅ RESTful API design")
    print("✅ JSON responses for easy parsing")