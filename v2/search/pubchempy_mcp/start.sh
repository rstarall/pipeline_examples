#!/bin/bash

# PubChemPy FastMCP Server Startup Script

set -e  # Exit on any error

echo "🧪 Starting PubChemPy FastMCP Server..."

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.11 or higher."
    exit 1
fi

# Check if pip is available
if ! command -v pip &> /dev/null && ! command -v pip3 &> /dev/null; then
    echo "❌ pip is not installed. Please install pip."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "🔧 Activating virtual environment..."
source venv/bin/activate

# Install/upgrade dependencies
echo "📥 Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Install requests for native client (optional)
echo "📦 Installing requests for native client..."
pip install requests

# Set environment variables
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

echo "🚀 FastMCP Server configuration:"
echo "  Framework: FastMCP 2.0"
echo "  Protocol: Model Context Protocol"
echo "  Transport: HTTP only"
echo "  Port: ${PORT:-8989}"
echo "  Available Tools: search_chemical"
echo "  Available Resources: health://status, server://info"

# Start the FastMCP server
echo "🌟 Starting FastMCP Server..."
echo "📝 Note: This server uses HTTP transport for web API access."
echo "   Server will be available at http://localhost:${PORT:-8989}"
echo ""

python src/mcp_server.py 