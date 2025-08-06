# Semantic Scholar MCP Server

A FastMCP server providing academic paper search capabilities using Semantic Scholar API with comprehensive paper metadata retrieval.

## Features

- **Comprehensive Paper Search**: Search for papers using Semantic Scholar's extensive academic database
- **Rich Metadata**: Retrieve detailed paper information including:
  - Citations and reference counts
  - Open access PDF links
  - Journal information
  - Author details
  - Publication types and dates
  - TL;DR summaries
  - Fields of study
- **Proxy API Support**: Uses a proxy API for enhanced reliability and performance
- **Structured JSON Response**: Well-formatted paper information with complete metadata
- **MCP Integration**: Compatible with MCP clients and pipelines
- **API Key Embedded**: Pre-configured with API key for immediate use

## API

### MCP Tools

- **`search_papers`**: Search for academic papers with comprehensive metadata retrieval

### HTTP Endpoints

- `POST /api/search/papers` - Direct paper search API
- `GET /api/health` - Health check endpoint

## Usage Examples

### Basic Paper Search
```python
# Search for papers about "machine learning"
result = await search_papers("machine learning", limit=10)
```

### Advanced Search with Pagination
```python
# Search with pagination
result = await search_papers(
    query="deep learning computer vision",
    limit=20,
    offset=20  # Skip first 20 results
)
```

### HTTP API Usage
```bash
curl -X POST "http://localhost:8992/api/search/papers" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "generative AI",
    "limit": 15,
    "offset": 0
  }'
```

## Response Format

Each paper result includes:
- `paperId`: Semantic Scholar paper ID
- `title`: Paper title
- `abstract`: Paper abstract
- `authors`: List of authors with IDs and names
- `venue`: Publication venue
- `year`: Publication year
- `citationCount`: Number of citations
- `referenceCount`: Number of references
- `isOpenAccess`: Whether paper is open access
- `openAccessPdf`: PDF download information
- `journal`: Journal details (name, volume, pages)
- `tldr`: AI-generated summary
- `fieldsOfStudy`: Research fields
- `publicationTypes`: Type of publication
- `externalIds`: DOI and other identifiers

## Installation & Deployment

### Using Docker Compose (Recommended)

1. Clone or download this project
2. Navigate to the project directory
3. Run:
```bash
docker-compose up -d
```

The server will be available at `http://localhost:8992`

### Using Docker

```bash
# Build the image
docker build -t semanticscholar-mcp .

# Run the container
docker run -p 8992:8992 semanticscholar-mcp
```

### Local Development

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the server:
```bash
python src/mcp_server.py
```

## Configuration

### API Configuration
- **API Key**: Pre-configured in the code (`SEMANTIC_SCHOLAR_API_KEY`)
- **Proxy URL**: Uses `https://lifuai.com/api/v1/graph/v1/paper/search`
- **Port**: Default port is `8992`

### Environment Variables
- `PORT`: Server port (default: 8992)
- `PYTHONPATH`: Python path (set to `/app` in Docker)
- `PYTHONUNBUFFERED`: Python output buffering (set to `1`)

## API Limits
- Maximum results per query: 100
- Default results: 10
- Pagination supported via `offset` parameter

## Health Check
Check server status:
```bash
curl http://localhost:8992/api/health
```

## Error Handling
The server includes comprehensive error handling:
- Invalid query validation
- API rate limit handling
- Network error recovery
- Structured error responses

## Development

### Project Structure
```
semanticscholar_mcp/
├── src/
│   └── mcp_server.py      # Main MCP server implementation
├── requirements.txt        # Python dependencies
├── Dockerfile             # Docker container definition
├── docker-compose.yml     # Docker Compose configuration
└── README.md              # This file
```

### Key Components
- `SemanticScholarAPI`: API client class
- `PaperInfo`: Data model for paper information
- `search_papers`: Main MCP tool for paper search
- Health check and error handling

## License
This project is provided as-is for research and educational purposes.

## Support
For issues or questions, please check the logs via:
```bash
docker-compose logs -f semanticscholar-fastmcp
```