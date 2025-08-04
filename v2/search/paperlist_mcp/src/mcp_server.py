#!/usr/bin/env python3
"""
Paperlist FastMCP Server

A FastMCP server providing academic paper search capabilities
using Paperlist API.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import os

import aiohttp
from pydantic import BaseModel
from fastmcp import FastMCP, Context
from starlette.requests import Request
from starlette.responses import JSONResponse
from urllib.parse import urlencode

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Data models
class PaperInfo(BaseModel):
    id: Optional[int] = None
    title: Optional[str] = None
    authors: Optional[str] = None
    year: Optional[int] = None
    citations: Optional[int] = None
    abstract: Optional[str] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    arxiv_pdf_url: Optional[str] = None
    semantic_scholar_id: Optional[str] = None
    dblp_id: Optional[str] = None
    pubmed_id: Optional[str] = None
    pmc_id: Optional[str] = None
    venue: Optional[str] = None
    topic: Optional[str] = None

class PaperSearchResponse(BaseModel):
    success: bool
    query: str
    total_count: int
    results: List[PaperInfo] = []
    error: Optional[str] = None
    source: str = "paperlist"

# Create FastMCP server instance
mcp = FastMCP("paperlist-mcp-server")

# Global HTTP client
http_client = None

async def get_http_client():
    """Get or create HTTP client"""
    global http_client
    if http_client is None:
        http_client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30.0))
    return http_client

async def cleanup_http_client():
    """Cleanup HTTP client"""
    global http_client
    if http_client:
        await http_client.close()
        http_client = None

class PaperlistAPI:
    """Paperlist API client integrated into MCP server"""
    
    BASE_URL = "https://www.papelist.app/api"
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
    
    async def search_papers(
        self,
        search_value: str,
        topic: str = "0.",
        year_min: int = -1,
        year_max: int = -1,
        infl_field: str = "n_cits",
        infl_min: int = -1,
        sort_by: str = "year-dsc",
        page_size: int = 50,
        page_ndx: int = 0
    ) -> Dict[str, Any]:
        """Search papers by keyword"""
        
        params = {
            "topic": topic,
            "year_min": year_min,
            "year_max": year_max,
            "infl_field": infl_field,
            "infl_min": infl_min,
            "search_value": search_value,
            "sort_by": sort_by,
            "page_size": page_size,
            "page_ndx": page_ndx
        }
        
        url = f"{self.BASE_URL}/paper?{urlencode(params)}"
        
        async with self.session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                logger.info(f"Found {data.get('count', 0)} papers for query: {search_value}")
                return data
            else:
                raise Exception(f"Search API error: {response.status}")
    
    async def get_paper_detail(self, paper_id: int) -> Dict[str, Any]:
        """Get detailed information for a single paper"""
        
        url = f"{self.BASE_URL}/detail?id={paper_id}"
        
        async with self.session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                logger.debug(f"Retrieved details for paper ID: {paper_id}")
                return data
            else:
                logger.warning(f"Detail API error for paper {paper_id}: {response.status}")
                return {}
    
    async def get_papers_details_concurrent(
        self, 
        paper_ids: List[int], 
        max_concurrent: int = 10
    ) -> List[Dict[str, Any]]:
        """Get detailed information for multiple papers concurrently"""
        
        semaphore = asyncio.Semaphore(max_concurrent)
        
        async def fetch_detail(paper_id: int) -> Dict[str, Any]:
            async with semaphore:
                try:
                    return await self.get_paper_detail(paper_id)
                except Exception as e:
                    logger.error(f"Failed to get detail for paper {paper_id}: {e}")
                    return {}
        
        tasks = [fetch_detail(paper_id) for paper_id in paper_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Filter out exceptions
        valid_results = [r for r in results if isinstance(r, dict)]
        logger.info(f"Retrieved details for {len(valid_results)} papers")
        return valid_results

def create_paper_info(paper: Dict[str, Any], detail: Dict[str, Any] = None) -> PaperInfo:
    """Create PaperInfo from API response data"""
    if detail is None:
        detail = {}
    
    arxiv_id = detail.get("id_arxiv", "")
    
    return PaperInfo(
        id=paper.get("id"),
        title=paper.get("title"),
        authors=paper.get("authors"),
        year=paper.get("year"),
        citations=paper.get("cits_n"),
        abstract=detail.get("abstr", ""),
        doi=detail.get("id_doi", ""),
        arxiv_id=arxiv_id,
        arxiv_pdf_url=f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
        semantic_scholar_id=detail.get("id_s2", ""),
        dblp_id=detail.get("id_dblp", ""),
        pubmed_id=detail.get("id_pm", ""),
        pmc_id=detail.get("id_pmc", ""),
        venue=paper.get("venue", ""),
        topic=paper.get("topic", "")
    )

@mcp.tool(tags={"search", "academic", "public"})
async def search_papers(
    query: str,
    page_size: int = 20,
    year_min: int = -1,
    year_max: int = -1,
    sort_by: str = "year-dsc",
    include_abstracts: bool = True,
    max_concurrent: int = 10,
    ctx: Context = None
) -> dict:
    """
    Search for academic papers by query string.
    
    Args:
        query: Search query string (paper title, keywords, etc.)
        page_size: Number of papers to return (max 50)
        year_min: Minimum publication year (-1 for no limit)
        year_max: Maximum publication year (-1 for no limit)
        sort_by: Sort order - 'year-dsc', 'year-asc', 'cits-dsc', 'cits-asc'
        include_abstracts: Whether to fetch paper abstracts (slower but more detailed)
        max_concurrent: Maximum concurrent API calls for fetching details
    
    Returns:
        JSON response with paper information and abstracts
    """
    if ctx:
        await ctx.info(f"Searching for papers: {query}")
    
    if page_size > 50:
        page_size = 50
        if ctx:
            await ctx.warning("Page size limited to 50")
    
    try:
        client = await get_http_client()
        api = PaperlistAPI(client)
        
        # Step 1: Search for papers
        search_results = await api.search_papers(
            search_value=query,
            page_size=page_size,
            year_min=year_min,
            year_max=year_max,
            sort_by=sort_by
        )
        
        papers = search_results.get("page", [])
        if not papers:
            return {
                "success": False,
                "query": query,
                "total_count": 0,
                "results": [],
                "error": "No papers found",
                "source": "paperlist"
            }
        
        total_count = search_results.get("count", len(papers))
        
        # Step 2: Get detailed information if requested
        paper_infos = []
        if include_abstracts:
            if ctx:
                await ctx.info(f"Fetching abstracts for {len(papers)} papers...")
            
            paper_ids = [paper["id"] for paper in papers]
            details = await api.get_papers_details_concurrent(
                paper_ids, 
                max_concurrent=max_concurrent
            )
            
            # Combine results
            for paper, detail in zip(papers, details):
                paper_info = create_paper_info(paper, detail)
                paper_infos.append(paper_info)
        else:
            # Create paper info without details
            for paper in papers:
                paper_info = create_paper_info(paper)
                paper_infos.append(paper_info)
        
        # Create response
        response = PaperSearchResponse(
            success=True,
            query=query,
            total_count=total_count,
            results=paper_infos
        )
        
        # Convert PaperInfo objects to dictionaries for JSON serialization
        results_dict = []
        for paper in response.results:
            paper_dict = {
                "id": paper.id,
                "title": paper.title,
                "authors": paper.authors,
                "year": paper.year,
                "citations": paper.citations,
                "abstract": paper.abstract,
                "doi": paper.doi,
                "arxiv_id": paper.arxiv_id,
                "arxiv_pdf_url": paper.arxiv_pdf_url,
                "semantic_scholar_id": paper.semantic_scholar_id,
                "dblp_id": paper.dblp_id,
                "pubmed_id": paper.pubmed_id,
                "pmc_id": paper.pmc_id,
                "venue": paper.venue,
                "topic": paper.topic
            }
            results_dict.append(paper_dict)
        
        if ctx:
            await ctx.info(f"Successfully returned {len(response.results)} papers")
        
        # Return JSON response
        return {
            "success": response.success,
            "query": response.query,
            "total_count": response.total_count,
            "results": results_dict,
            "source": response.source,
            "error": None
        }
        
    except Exception as e:
        error_msg = f"Paper Search Error: {str(e)}"
        if ctx:
            await ctx.error(error_msg)
        logger.error(f"Paper search failed: {str(e)}")
        return {
            "success": False,
            "query": query,
            "total_count": 0,
            "results": [],
            "source": "paperlist",
            "error": error_msg
        }

@mcp.tool(tags={"search", "academic", "public"})
async def get_paper_details(
    paper_id: int,
    ctx: Context = None
) -> dict:
    """
    Get detailed information for a specific paper by ID.
    
    Args:
        paper_id: Paperlist paper ID
    
    Returns:
        JSON response with paper details including full abstract
    """
    if ctx:
        await ctx.info(f"Fetching details for paper ID: {paper_id}")
    
    try:
        client = await get_http_client()
        api = PaperlistAPI(client)
        
        detail = await api.get_paper_detail(paper_id)
        
        if not detail:
            return {
                "success": False,
                "paper_id": paper_id,
                "error": "No details found for this paper ID",
                "source": "paperlist"
            }
        
        # Create paper detail response
        paper_detail = {
            "id": paper_id,
            "title": detail.get("title"),
            "authors": detail.get("authors"),
            "year": detail.get("year"),
            "venue": detail.get("venue"),
            "abstract": detail.get("abstr"),
            "citations": detail.get("cits_n"),
            "doi": detail.get("id_doi"),
            "arxiv_id": detail.get("id_arxiv"),
            "arxiv_pdf_url": f"https://arxiv.org/pdf/{detail.get('id_arxiv')}" if detail.get("id_arxiv") else None,
            "semantic_scholar_id": detail.get("id_s2"),
            "dblp_id": detail.get("id_dblp"),
            "pubmed_id": detail.get("id_pm"),
            "pmc_id": detail.get("id_pmc"),
            "topic": detail.get("topic")
        }
        
        if ctx:
            await ctx.info("Successfully retrieved paper details")
        
        # Return JSON response
        return {
            "success": True,
            "paper_id": paper_id,
            "result": paper_detail,
            "source": "paperlist",
            "error": None
        }
        
    except Exception as e:
        error_msg = f"Error fetching paper details: {str(e)}"
        if ctx:
            await ctx.error(error_msg)
        logger.error(f"Paper detail fetch failed: {str(e)}")
        return {
            "success": False,
            "paper_id": paper_id,
            "result": None,
            "source": "paperlist",
            "error": error_msg
        }



# Custom HTTP endpoints
@mcp.custom_route("/api/search/papers", methods=["POST"])
async def search_papers_api(request: Request) -> JSONResponse:
    """Direct API endpoint for paper search"""
    try:
        body = await request.json()
        query = body.get("query", "")
        page_size = body.get("page_size", 20)
        include_abstracts = body.get("include_abstracts", True)
        
        if not query:
            return JSONResponse(
                {"error": "Query parameter is required"}, 
                status_code=400
            )
        
        result = await search_papers(
            query=query,
            page_size=page_size,
            include_abstracts=include_abstracts,
            ctx=None
        )
        
        return JSONResponse({
            "success": True,
            "query": query,
            "result": result,
            "endpoint": "custom_api",
            "tags_used": ["search", "academic"]
        })
        
    except Exception as e:
        logger.error(f"Error in search_papers_api: {e}")
        return JSONResponse(
            {"error": f"Search failed: {str(e)}"}, 
            status_code=500
        )

# Removed custom tag-based API endpoints - tool discovery and filtering
# is now handled in the pipeline layer



@mcp.custom_route("/api/health", methods=["GET"])
async def api_health_check(request: Request) -> JSONResponse:
    """API health check endpoint"""
    return JSONResponse({
        "status": "healthy",
        "service": "Paperlist FastMCP Server",
        "version": "1.0.0",
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
        port = int(os.getenv("PORT", "8990"))
        logger.info(f"Starting Paperlist FastMCP Server on HTTP transport at port {port}...")
        mcp.run(transport="http", host="0.0.0.0", port=port)
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        exit(1)