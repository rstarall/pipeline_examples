# Paperlist MCP Server

A FastMCP server providing academic paper search capabilities using the Paperlist API.

## Features

- **Academic Paper Search**: Search for papers by keywords, title, or author names
- **Abstract Retrieval**: Fetch full abstracts and detailed information
- **Year Filtering**: Filter results by publication year range
- **Citation Sorting**: Sort by publication year or citation count
- **Multiple ID Support**: Access papers via DOI, ArXiv ID, Semantic Scholar, etc.
- **Concurrent Processing**: Fast parallel fetching of paper details

## API

### MCP Tools

- **`search_papers`**: Search for academic papers with filtering and abstract retrieval
- **`get_paper_details`**: Get detailed information for a specific paper by ID

### HTTP Endpoints

- `POST /api/search/papers` - Direct paper search API
- `GET /api/health` - Health check endpoint

## Usage Examples

### Basic Search
```python
# Search for papers about machine learning
result = await search_papers("machine learning", page_size=10)
```

### Advanced Search with Filtering
```python
# Search recent papers with high citations
result = await search_papers(
    query="deep learning",
    page_size=20,
    year_min=2020,
    year_max=2024,
    sort_by="cits-dsc",
    include_abstracts=True
)
```

### Get Paper Details
```python
# Get full details for a specific paper
details = await get_paper_details(paper_id=12345)
```

## Installation

### Using Docker
```bash
cd v2/search/paperlist_mcp
docker build -t paperlist-mcp .
docker run -p 8990:8990 paperlist-mcp
```

### Local Installation
```bash
cd v2/search/paperlist_mcp
pip install -r requirements.txt
python src/mcp_server.py
```

## Configuration

Environment variables:
- `PORT`: Server port (default: 8990)

## Search Parameters

- **query**: Search terms (keywords, title, author names)
- **page_size**: Number of results (1-50, default 20)
- **year_min/year_max**: Publication year range (-1 for no limit)
- **sort_by**: Sort order
  - `year-dsc`: Year descending (newest first)
  - `year-asc`: Year ascending (oldest first)
  - `cits-dsc`: Citations descending (most cited first)  
  - `cits-asc`: Citations ascending (least cited first)
- **include_abstracts**: Fetch full abstracts (default: true)
- **max_concurrent**: Max concurrent API calls (default: 10)

## Output Format

Each paper result includes:
- Title and authors
- Publication year and venue
- Citation count
- Abstract (if requested)
- External links (DOI, ArXiv, Semantic Scholar, etc.)

## Data Source

This server uses the [Paperlist.app](https://www.papelist.app) API to search and retrieve academic paper information.

## Health Check

The server provides a simple health check at `/api/health` endpoint.

## Summary

This is a focused MCP server implementation with:
- ✅ Clean, minimal codebase
- ✅ Two core tools for paper search and detail retrieval  
- ✅ Docker support with health checks
- ✅ Concurrent processing for fast abstract fetching
- ✅ No unnecessary resource endpoints or complexity