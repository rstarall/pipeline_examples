FROM python:3.11-slim

LABEL org.opencontainers.image.title="Paperlist FastMCP Server"
LABEL org.opencontainers.image.description="FastMCP server for academic paper search via Paperlist API"
LABEL org.opencontainers.image.version="1.0.0"

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ ./src/

# Create non-root user
RUN useradd --create-home --shell /bin/bash mcp
RUN chown -R mcp:mcp /app
USER mcp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8990/api/health || exit 1

# Expose port
EXPOSE 8990

# Set environment variables
ENV PORT=8990
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Run the server
CMD ["python", "src/mcp_server.py"]