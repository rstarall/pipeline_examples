#!/usr/bin/env python3
"""
Semantic Scholar FastMCP Server

A FastMCP server providing academic paper search capabilities
using Semantic Scholar API with proxy support for enhanced search functionality.
"""

import asyncio
import logging
import json
import os
from typing import Any, Dict, List, Optional
from datetime import datetime

import aiohttp
from pydantic import BaseModel
from fastmcp import FastMCP, Context
from starlette.requests import Request
from starlette.responses import JSONResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Semantic Scholar API configuration
SEMANTIC_SCHOLAR_API_KEY = "sk-user-D499F926CD23FACD63C62D59E4038CCC"
SEMANTIC_SCHOLAR_PROXY_URL = "https://lifuai.com/api/v1/graph/v1/paper/search"

# Data models
class AuthorInfo(BaseModel):
    authorId: Optional[str] = None
    name: Optional[str] = None

class JournalInfo(BaseModel):
    name: Optional[str] = None
    pages: Optional[str] = None
    volume: Optional[str] = None

class OpenAccessPdf(BaseModel):
    url: Optional[str] = None
    status: Optional[str] = None
    license: Optional[str] = None

class TldrInfo(BaseModel):
    model: Optional[str] = None
    text: Optional[str] = None

class ExternalIds(BaseModel):
    DOI: Optional[str] = None
    CorpusId: Optional[int] = None

class PaperInfo(BaseModel):
    paperId: Optional[str] = None
    externalIds: Optional[ExternalIds] = None
    url: Optional[str] = None
    title: Optional[str] = None
    abstract: Optional[str] = None
    venue: Optional[str] = None
    year: Optional[int] = None
    referenceCount: Optional[int] = None
    citationCount: Optional[int] = None
    influentialCitationCount: Optional[int] = None
    isOpenAccess: Optional[bool] = None
    openAccessPdf: Optional[OpenAccessPdf] = None
    fieldsOfStudy: Optional[List[str]] = []
    tldr: Optional[TldrInfo] = None
    publicationTypes: Optional[List[str]] = []
    publicationDate: Optional[str] = None
    journal: Optional[JournalInfo] = None
    authors: Optional[List[AuthorInfo]] = []

class PaperSearchResponse(BaseModel):
    success: bool
    query: str
    total_count: int
    results: List[PaperInfo] = []
    error: Optional[str] = None
    source: str = "semantic_scholar"

# Create FastMCP server instance
mcp = FastMCP("semantic-scholar-mcp-server")

# Global HTTP client
http_client = None

async def get_http_client():
    """Get or create HTTP client"""
    global http_client
    if http_client is None:
        connector = aiohttp.TCPConnector(
            limit=10,
            limit_per_host=5,
            ttl_dns_cache=300,
            use_dns_cache=True,
        )
        
        headers = {
            'User-Agent': 'SemanticScholar-MCP-Bot/1.0 (research@example.com)',
            'Accept': 'application/json',
            'Connection': 'keep-alive',
            'Authorization': f'Bearer {SEMANTIC_SCHOLAR_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        timeout = aiohttp.ClientTimeout(total=60, connect=10)
        
        http_client = aiohttp.ClientSession(
            connector=connector, 
            headers=headers, 
            timeout=timeout
        )
    return http_client

async def cleanup_http_client():
    """Cleanup HTTP client"""
    global http_client
    if http_client:
        await http_client.close()
        http_client = None

class SemanticScholarAPI:
    """Semantic Scholar API client with proxy support"""
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
    
    async def search_papers(
        self,
        query: str,
        limit: int = 10,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Search papers using Semantic Scholar proxy API"""
        
        # Define fields to retrieve
        fields = 'paperId,title,abstract,venue,year,referenceCount,citationCount,influentialCitationCount,isOpenAccess,openAccessPdf,fieldsOfStudy,url,externalIds,tldr,publicationTypes,publicationDate,journal,authors'
        sub_fields = 'paperId,title,abstract,venue,year,referenceCount,citationCount,influentialCitationCount,isOpenAccess,openAccessPdf,fieldsOfStudy,url,externalIds,publicationTypes,publicationDate,journal,authors'
        params = {
            'query': query,
            'limit': limit,
            'offset': offset,
            'fields': sub_fields
        }
        
        try:
            logger.info(f"Searching papers with query: '{query}', limit: {limit}, offset: {offset}")
            
            async with self.session.get(
                SEMANTIC_SCHOLAR_PROXY_URL,
                params=params
            ) as response:
                response.raise_for_status()
                data = await response.json()
                
                logger.info(f"API response: Found {data.get('total', 0)} papers")
                return data
                
        except aiohttp.ClientError as e:
            logger.error(f"HTTP request failed: {e}")
            raise
        except Exception as e:
            logger.error(f"Search request failed: {e}")
            raise

    def parse_paper_info(self, paper_data: Dict[str, Any]) -> PaperInfo:
        """Parse paper data from API response into PaperInfo model"""
        try:
            # Parse external IDs
            external_ids = None
            if paper_data.get('externalIds'):
                external_ids = ExternalIds(
                    DOI=paper_data['externalIds'].get('DOI'),
                    CorpusId=paper_data['externalIds'].get('CorpusId')
                )
            
            # Parse open access PDF info
            open_access_pdf = None
            if paper_data.get('openAccessPdf'):
                open_access_pdf = OpenAccessPdf(
                    url=paper_data['openAccessPdf'].get('url'),
                    status=paper_data['openAccessPdf'].get('status'),
                    license=paper_data['openAccessPdf'].get('license')
                )
            
            # Parse TLDR
            tldr = None
            if paper_data.get('tldr'):
                tldr = TldrInfo(
                    model=paper_data['tldr'].get('model'),
                    text=paper_data['tldr'].get('text')
                )
            
            # Parse journal info
            journal = None
            if paper_data.get('journal'):
                journal = JournalInfo(
                    name=paper_data['journal'].get('name'),
                    pages=paper_data['journal'].get('pages'),
                    volume=paper_data['journal'].get('volume')
                )
            
            # Parse authors
            authors = []
            if paper_data.get('authors'):
                for author_data in paper_data['authors']:
                    author = AuthorInfo(
                        authorId=author_data.get('authorId'),
                        name=author_data.get('name')
                    )
                    authors.append(author)
            
            return PaperInfo(
                paperId=paper_data.get('paperId'),
                externalIds=external_ids,
                url=paper_data.get('url'),
                title=paper_data.get('title'),
                abstract=paper_data.get('abstract'),
                venue=paper_data.get('venue'),
                year=paper_data.get('year'),
                referenceCount=paper_data.get('referenceCount'),
                citationCount=paper_data.get('citationCount'),
                influentialCitationCount=paper_data.get('influentialCitationCount'),
                isOpenAccess=paper_data.get('isOpenAccess'),
                openAccessPdf=open_access_pdf,
                fieldsOfStudy=paper_data.get('fieldsOfStudy', []),
                tldr=tldr,
                publicationTypes=paper_data.get('publicationTypes', []),
                publicationDate=paper_data.get('publicationDate'),
                journal=journal,
                authors=authors
            )
            
        except Exception as e:
            logger.error(f"Failed to parse paper data: {e}")
            # Return basic paper info on parse error
            return PaperInfo(
                paperId=paper_data.get('paperId'),
                title=paper_data.get('title', 'Title unavailable'),
                abstract=paper_data.get('abstract', 'Abstract unavailable')
            )

# MCP Tool: search_papers
@mcp.tool()
async def search_papers(
    query: str,
    limit: int = 10,
    offset: int = 0,
    ctx: Context = None
) -> Dict[str, Any]:
    """Search for academic papers using Semantic Scholar API
    
    Args:
        query: The search query string
        limit: Maximum number of results to return (default: 10, max: 100)
        offset: Number of results to skip for pagination (default: 0)
        
    Returns:
        Dictionary containing search results with paper information
    """
    try:
        if ctx:
            await ctx.info(f"Searching papers with query: '{query}' (limit: {limit}, offset: {offset})")
        
        # Validate parameters
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty")
        
        limit = max(1, min(limit, 100))  # Clamp between 1 and 100
        offset = max(0, offset)
        
        # Get HTTP client and API instance
        session = await get_http_client()
        api = SemanticScholarAPI(session)
        
        # Perform search
        response_data = await api.search_papers(query.strip(), limit, offset)
        
        # Parse results
        papers = []
        for paper_data in response_data.get('data', []):
            paper = api.parse_paper_info(paper_data)
            papers.append(paper)
        
        # Create response
        response = PaperSearchResponse(
            success=True,
            query=query,
            total_count=response_data.get('total', len(papers)),
            results=papers,
            source="semantic_scholar"
        )
        
        if ctx:
            await ctx.info(f"Found {len(papers)} papers (total available: {response.total_count})")
        
        # Convert to JSON-serializable format
        results_dict = []
        for paper in response.results:
            paper_dict = {
                "paperId": paper.paperId,
                "title": paper.title,
                "abstract": paper.abstract,
                "url": paper.url,
                "venue": paper.venue,
                "year": paper.year,
                "referenceCount": paper.referenceCount,
                "citationCount": paper.citationCount,
                "influentialCitationCount": paper.influentialCitationCount,
                "isOpenAccess": paper.isOpenAccess,
                "fieldsOfStudy": paper.fieldsOfStudy,
                "publicationTypes": paper.publicationTypes,
                "publicationDate": paper.publicationDate,
                "externalIds": paper.externalIds.dict() if paper.externalIds else None,
                "openAccessPdf": paper.openAccessPdf.dict() if paper.openAccessPdf else None,
                "tldr": paper.tldr.dict() if paper.tldr else None,
                "journal": paper.journal.dict() if paper.journal else None,
                "authors": [author.dict() for author in paper.authors] if paper.authors else []
            }
            results_dict.append(paper_dict)
        
        return {
            "success": response.success,
            "query": response.query,
            "total_count": response.total_count,
            "results": results_dict,
            "source": response.source,
            "error": None
        }
        
    except Exception as e:
        error_msg = f"Semantic Scholar Search Error: {str(e)}"
        if ctx:
            await ctx.error(error_msg)
        logger.error(f"Paper search failed: {str(e)}")
        return {
            "success": False,
            "query": query,
            "total_count": 0,
            "results": [],
            "source": "semantic_scholar",
            "error": error_msg
        }

# Custom HTTP endpoints
@mcp.custom_route("/api/search/papers", methods=["POST"])
async def search_papers_api(request: Request) -> JSONResponse:
    """Direct API endpoint for paper search"""
    try:
        body = await request.json()
        query = body.get("query", "")
        limit = body.get("limit", 10)
        offset = body.get("offset", 0)
        
        if not query:
            return JSONResponse(
                {"error": "Query parameter is required"}, 
                status_code=400
            )
        
        result = await search_papers(
            query=query,
            limit=limit,
            offset=offset,
            ctx=None
        )
        
        return JSONResponse({
            "success": True,
            "query": query,
            "result": result,
            "endpoint": "custom_api",
            "tags_used": ["search", "academic", "semantic_scholar"]
        })
        
    except Exception as e:
        logger.error(f"Error in search_papers_api: {e}")
        return JSONResponse(
            {"error": f"Search failed: {str(e)}"}, 
            status_code=500
        )

@mcp.custom_route("/api/health", methods=["GET"])
async def api_health_check(request: Request) -> JSONResponse:
    """API health check endpoint"""
    return JSONResponse({
        "status": "healthy",
        "service": "Semantic Scholar FastMCP Server",
        "version": "1.0.0",
        "api_key_configured": bool(SEMANTIC_SCHOLAR_API_KEY),
        "features": [
            "Academic paper search",
            "Semantic Scholar API integration",
            "Comprehensive paper metadata",
            "Proxy API support"
        ],
        "endpoints": {
            "mcp": "/mcp",
            "search_papers": "/api/search/papers",
            "health": "/api/health"
        }
    })

async def cleanup():
    """Cleanup resources on shutdown"""
    try:
        await cleanup_http_client()
        logger.info("Cleanup completed successfully")
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")

if __name__ == "__main__":
    try:
        # Register cleanup function
        import atexit
        import signal
        
        def sync_cleanup():
            asyncio.run(cleanup())
            
        atexit.register(sync_cleanup)
        
        # Handle signals
        def signal_handler(signum, frame):
            logger.info("Received shutdown signal")
            asyncio.run(cleanup())
            exit(0)
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Run the server
        port = int(os.getenv("PORT", "8992"))
        logger.info(f"Starting Semantic Scholar FastMCP Server on HTTP transport at port {port}...")
        logger.info(f"API Key configured: {bool(SEMANTIC_SCHOLAR_API_KEY)}")
        mcp.run(transport="http", host="0.0.0.0", port=port)
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        exit(1)