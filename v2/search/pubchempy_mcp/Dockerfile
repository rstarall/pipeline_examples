FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash mcpuser && \
    chown -R mcpuser:mcpuser /app
USER mcpuser

# Set environment variables
ENV PYTHONPATH=/app

# Expose port for HTTP transport (optional)
EXPOSE 8989

# Run the FastMCP server
CMD ["python", "src/mcp_server.py"] 