#!/bin/bash

# PubChemPy MCP Server Startup Script

set -e  # Exit on any error

echo "🧪 Starting PubChemPy MCP Server..."

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

# Create logs directory if it doesn't exist
mkdir -p logs

# Set environment variables
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
export LOG_LEVEL="${LOG_LEVEL:-info}"

echo "🌐 MCP Server configuration:"
echo "  Protocol: Model Context Protocol (stdio)"
echo "  Log Level: $LOG_LEVEL"
echo "  Available Tools: search_chemical"

# Start the MCP server
echo "🚀 Starting MCP Server..."
echo "📝 Note: This server uses stdio protocol for MCP communication."
echo "   Connect it to your LLM client that supports MCP protocol."
echo ""

python -m src.mcp_server 