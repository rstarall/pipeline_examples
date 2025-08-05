# PubTator3 MCP Server

A FastMCP server providing academic paper search capabilities using PubTator3 API with abstract-based search and multi-source abstract retrieval.

## Features

- **Abstract-Based Search**: Search for papers by abstract content using PubTator3 API
- **Multi-Source Abstract Retrieval**: Fetch full abstracts from multiple academic databases
  - Semantic Scholar API (primary source)
  - OpenAlex API (open academic database)  
  - CrossRef API (DOI-based lookup)
- **Concurrent Processing**: Fast parallel fetching of abstracts with rate limiting
- **Structured JSON Response**: Well-formatted paper information with metadata
- **MCP Integration**: Compatible with MCP clients and pipelines

## API

### MCP Tools

- **`search_papers_by_abstract`**: Search for academic papers by abstract content with multi-source abstract retrieval

### HTTP Endpoints

- `POST /api/search/abstract` - Direct abstract-based paper search API
- `GET /api/health` - Health check endpoint

## Usage Examples

### Basic Abstract Search
```python
# Search for papers with "machine learning" in abstracts
result = await search_papers_by_abstract("machine learning", page_size=10)
```

### Advanced Search with Full Abstracts
```python
# Search with full abstract retrieval from multiple sources
result = await search_papers_by_abstract(
    query="deep learning medical imaging",
    page_size=20,
    page=1,
    include_full_abstracts=True,
    max_concurrent=3
)
```

### HTTP API Usage
```bash
curl -X POST "http://localhost:8991/api/search/abstract" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "CRISPR gene editing",
    "page_size": 15,
    "include_full_abstracts": true
  }'
```

## Response Format

```json
{
  "success": true,
  "query": "machine learning",
  "total_count": 10,
  "results": [
    {
      "pmid": "12345678",
      "title": "Paper Title",
      "authors": ["Author 1", "Author 2"],
      "journal": "Nature",
      "date": "2024-01-15",
      "doi": "10.1038/example",
      "abstract": "Full abstract text...",
      "abstract_source": "Semantic Scholar"
    }
  ],
  "source": "pubtator3",
  "error": null
}
```

## Installation

### Using Docker (Recommended)

```bash
# Clone and navigate to project
cd v2/search/pubtator3_mcp

# Build and run with Docker Compose
docker-compose up --build
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python src/mcp_server.py
```

## Configuration

The server runs on port 8991 by default. You can customize this with the `PORT` environment variable:

```bash
export PORT=8992
python src/mcp_server.py
```

## Architecture

- **PubTator3 API**: Primary search engine for finding papers by abstract content
- **Multi-Source Abstract Retrieval**: Fallback mechanism across multiple academic APIs
- **Async Processing**: Concurrent abstract fetching with configurable rate limiting
- **Error Handling**: Graceful degradation when abstract sources are unavailable

## Search Query Examples

The system supports PubTator3's abstract search syntax:

- Simple terms: `"machine learning"`
- Boolean operators: `"deep learning" AND "medical imaging"`
- Field-specific: `abstract:"neural network"`

## Limitations

- Rate limited to prevent API abuse
- Maximum 50 papers per request
- Abstract retrieval may fail for some papers depending on source availability
- Depends on external API availability (PubTator3, Semantic Scholar, OpenAlex, CrossRef)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## License

This project is licensed under the MIT License.