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
) -> str:
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
        Formatted search results with paper information and abstracts
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
            return f"📄 No papers found for query: {query}"
        
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
        
        # Format response
        response_text = f"📄 Academic Paper Search Results\n"
        response_text += f"Query: {response.query}\n"
        response_text += f"Found: {len(response.results)} papers (Total: {response.total_count})\n"
        response_text += f"Source: {response.source}\n\n"
        
        for i, paper in enumerate(response.results, 1):
            response_text += f"--- Paper {i} ---\n"
            
            if paper.title:
                response_text += f"Title: {paper.title}\n"
            if paper.authors:
                response_text += f"Authors: {paper.authors}\n"
            if paper.year:
                response_text += f"Year: {paper.year}\n"
            if paper.citations is not None:
                response_text += f"Citations: {paper.citations}\n"
            if paper.venue:
                response_text += f"Venue: {paper.venue}\n"
            
            # Abstract
            if paper.abstract:
                abstract_preview = paper.abstract[:300] + "..." if len(paper.abstract) > 300 else paper.abstract
                response_text += f"Abstract: {abstract_preview}\n"
            
            # External links
            links = []
            if paper.arxiv_id:
                links.append(f"ArXiv: https://arxiv.org/abs/{paper.arxiv_id}")
                if paper.arxiv_pdf_url:
                    links.append(f"PDF: {paper.arxiv_pdf_url}")
            if paper.doi:
                links.append(f"DOI: https://doi.org/{paper.doi}")
            if paper.semantic_scholar_id:
                links.append(f"Semantic Scholar: https://www.semanticscholar.org/paper/{paper.semantic_scholar_id}")
            
            if links:
                response_text += f"Links: {' | '.join(links)}\n"
            
            response_text += "\n"
        
        if ctx:
            await ctx.info(f"Successfully returned {len(response.results)} papers")
        
        return response_text
        
    except Exception as e:
        error_msg = f"❌ Paper Search Error: {str(e)}"
        if ctx:
            await ctx.error(error_msg)
        logger.error(f"Paper search failed: {str(e)}")
        return error_msg

@mcp.tool(tags={"search", "academic", "public"})
async def get_paper_details(
    paper_id: int,
    ctx: Context = None
) -> str:
    """
    Get detailed information for a specific paper by ID.
    
    Args:
        paper_id: Paperlist paper ID
    
    Returns:
        Formatted paper details including full abstract
    """
    if ctx:
        await ctx.info(f"Fetching details for paper ID: {paper_id}")
    
    try:
        client = await get_http_client()
        api = PaperlistAPI(client)
        
        detail = await api.get_paper_detail(paper_id)
        
        if not detail:
            return f"❌ No details found for paper ID: {paper_id}"
        
        # Format response
        response_text = f"📄 Paper Details\n"
        response_text += f"Paper ID: {paper_id}\n\n"
        
        if detail.get("title"):
            response_text += f"Title: {detail['title']}\n"
        if detail.get("authors"):
            response_text += f"Authors: {detail['authors']}\n"
        if detail.get("year"):
            response_text += f"Year: {detail['year']}\n"
        if detail.get("venue"):
            response_text += f"Venue: {detail['venue']}\n"
        if detail.get("abstr"):
            response_text += f"\nAbstract:\n{detail['abstr']}\n"
        
        # External IDs
        external_ids = []
        if detail.get("id_arxiv"):
            external_ids.append(f"ArXiv: {detail['id_arxiv']}")
        if detail.get("id_doi"):
            external_ids.append(f"DOI: {detail['id_doi']}")
        if detail.get("id_s2"):
            external_ids.append(f"Semantic Scholar: {detail['id_s2']}")
        if detail.get("id_dblp"):
            external_ids.append(f"DBLP: {detail['id_dblp']}")
        if detail.get("id_pm"):
            external_ids.append(f"PubMed: {detail['id_pm']}")
        if detail.get("id_pmc"):
            external_ids.append(f"PMC: {detail['id_pmc']}")
        
        if external_ids:
            response_text += f"\nExternal IDs:\n"
            for ext_id in external_ids:
                response_text += f"  {ext_id}\n"
        
        if ctx:
            await ctx.info("Successfully retrieved paper details")
        
        return response_text
        
    except Exception as e:
        error_msg = f"❌ Error fetching paper details: {str(e)}"
        if ctx:
            await ctx.error(error_msg)
        logger.error(f"Paper detail fetch failed: {str(e)}")
        return error_msg



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

@mcp.custom_route("/api/tags", methods=["GET"])
async def list_tags(request: Request) -> JSONResponse:
    """List all available tags from tools"""
    try:
        # Get all tools to extract tags
        tools = mcp.get_tools()
        
        tags = set()
        
        # Extract tags from tools
        for tool in tools:
            if hasattr(tool, 'tags') and tool.tags:
                tags.update(tool.tags)
        
        sorted_tags = sorted(list(tags))
        
        return JSONResponse({
            "success": True,
            "count": len(sorted_tags),
            "tags": sorted_tags
        })
        
    except Exception as e:
        logger.error(f"Error listing tags: {e}")
        return JSONResponse(
            {"error": f"Failed to list tags: {str(e)}"}, 
            status_code=500
        )

@mcp.custom_route("/api/tools/by-tag/{tag}", methods=["GET"])
async def get_tools_by_tag(request: Request) -> JSONResponse:
    """Get tools filtered by specific tag"""
    try:
        tag = request.path_params.get("tag")
        if not tag:
            return JSONResponse(
                {"error": "Tag parameter is required"}, 
                status_code=400
            )
        
        # Get all tools and filter by tag
        all_tools = mcp.get_tools()
        filtered_tools = []
        
        for tool in all_tools:
            if hasattr(tool, 'tags') and tool.tags and tag in tool.tags:
                tool_info = {
                    "name": tool.name,
                    "description": tool.description or "No description available",
                    "tags": list(tool.tags) if tool.tags else [],
                    "parameters": {}
                }
                
                # Add parameter information if available
                if hasattr(tool, 'input_schema') and tool.input_schema:
                    schema = tool.input_schema
                    if isinstance(schema, dict) and 'properties' in schema:
                        for param_name, param_info in schema['properties'].items():
                            tool_info["parameters"][param_name] = {
                                "type": param_info.get("type", "unknown"),
                                "description": param_info.get("description", "No description")
                            }
                
                filtered_tools.append(tool_info)
        
        return JSONResponse({
            "success": True,
            "tag": tag,
            "count": len(filtered_tools),
            "tools": filtered_tools
        })
        
    except Exception as e:
        logger.error(f"Error getting tools by tag: {e}")
        return JSONResponse(
            {"error": f"Failed to get tools by tag: {str(e)}"}, 
            status_code=500
        )

@mcp.custom_route("/api/health", methods=["GET"])
async def api_health_check(request: Request) -> JSONResponse:
    """API health check endpoint"""
    return JSONResponse({
        "status": "healthy",
        "service": "Paperlist FastMCP Server",
        "version": "1.0.0",
        "endpoints": {
            "mcp": "/mcp",
            "tools_by_tag": "/api/tools/by-tag/{tag}",
            "search_papers": "/api/search/papers",
            "list_tags": "/api/tags",
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