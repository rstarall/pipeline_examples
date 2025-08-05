#!/usr/bin/env python3
"""
PubTator3 FastMCP Server

A FastMCP server providing academic paper search capabilities
using PubTator3 API with abstract-based search and multi-source abstract retrieval.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional
import os

import aiohttp
from pydantic import BaseModel
from fastmcp import FastMCP, Context
from starlette.requests import Request
from starlette.responses import JSONResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Data models
class PaperInfo(BaseModel):
    pmid: Optional[str] = None
    title: Optional[str] = None
    authors: Optional[List[str]] = []
    journal: Optional[str] = None
    date: Optional[str] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None
    abstract_source: Optional[str] = None  # 记录摘要来源

class PaperSearchResponse(BaseModel):
    success: bool
    query: str
    total_count: int
    results: List[PaperInfo] = []
    error: Optional[str] = None
    source: str = "pubtator3"

# Create FastMCP server instance
mcp = FastMCP("pubtator3-mcp-server")

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
            'User-Agent': 'PubTator3-MCP-Bot/1.0 (research@example.com)',
            'Accept': 'application/json',
            'Connection': 'keep-alive'
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

class PubTator3API:
    """PubTator3 API client with multi-source abstract retrieval"""
    
    PUBTATOR3_BASE_URL = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"
    
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
    
    async def search_papers_by_abstract(
        self,
        query: str,
        page: int = 1,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """Search papers by abstract content using PubTator3"""
        
        search_url = f"{self.PUBTATOR3_BASE_URL}/search/"
        search_params = {
            'text': f'abstract:"{query}"',
            'page_size': page_size,
            'page': page
        }
        
        async with self.session.get(search_url, params=search_params) as response:
            if response.status == 200:
                data = await response.json()
                logger.info(f"Found {len(data.get('results', []))} papers for query: {query}")
                return data
            else:
                raise Exception(f"PubTator3 search API error: {response.status}")
    
    async def get_abstract_semantic_scholar(self, title: str, doi: str = None) -> tuple[str, str]:
        """Get abstract from Semantic Scholar API"""
        try:
            if doi:
                search_query = f'doi:"{doi}"'
            else:
                search_query = title.replace('"', '\\"')
            
            url = "https://api.semanticscholar.org/graph/v1/paper/search"
            params = {
                'query': search_query,
                'limit': 1,
                'fields': 'abstract,title,doi'
            }
            headers = {'Accept': 'application/json'}
            
            async with self.session.get(url, params=params, headers=headers, 
                                      timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    return f"Semantic Scholar API error: {response.status}", "error"
                    
                data = await response.json()
                
                if data.get('total', 0) > 0 and data.get('data'):
                    paper = data['data'][0]
                    abstract = paper.get('abstract', '').strip()
                    
                    if abstract:
                        return abstract, "Semantic Scholar"
                    else:
                        return "No abstract available in Semantic Scholar", "error"
                else:
                    return "Paper not found in Semantic Scholar", "error"
                    
        except Exception as e:
            logger.error(f"Semantic Scholar API error: {e}")
            return f"Semantic Scholar API error: {str(e)}", "error"
    
    async def get_abstract_openalex(self, title: str, doi: str = None) -> tuple[str, str]:
        """Get abstract from OpenAlex API"""
        try:
            url = "https://api.openalex.org/works"
            
            if doi:
                params = {
                    'filter': f'doi:{doi}',
                    'select': 'abstract_inverted_index,title,doi'
                }
            else:
                params = {
                    'search': title,
                    'select': 'abstract_inverted_index,title,doi',
                    'per_page': 1
                }
            
            headers = {'Accept': 'application/json', 'User-Agent': 'PubTator3-MCP-Bot/1.0'}
            
            async with self.session.get(url, params=params, headers=headers, 
                                      timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    return f"OpenAlex API error: {response.status}", "error"
                    
                data = await response.json()
                
                if data.get('results'):
                    paper = data['results'][0]
                    abstract_inverted = paper.get('abstract_inverted_index')
                    
                    if abstract_inverted:
                        abstract = self.reconstruct_abstract_from_inverted_index(abstract_inverted)
                        return abstract if abstract else "Abstract reconstruction failed", "OpenAlex" if abstract else "error"
                    else:
                        return "No abstract available in OpenAlex", "error"
                else:
                    return "Paper not found in OpenAlex", "error"
                    
        except Exception as e:
            logger.error(f"OpenAlex API error: {e}")
            return f"OpenAlex API error: {str(e)}", "error"
    
    async def get_abstract_crossref(self, doi: str) -> tuple[str, str]:
        """Get abstract from CrossRef API"""
        if not doi:
            return "DOI required for CrossRef", "error"
        
        try:
            url = f"https://api.crossref.org/works/{doi}"
            headers = {'Accept': 'application/json', 'User-Agent': 'PubTator3-MCP-Bot/1.0'}
            
            async with self.session.get(url, headers=headers, 
                                      timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status != 200:
                    return f"CrossRef API error: {response.status}", "error"
                    
                data = await response.json()
                message = data.get('message', {})
                abstract = message.get('abstract', '').strip()
                
                if abstract:
                    # Remove HTML tags if present
                    abstract = re.sub(r'<[^>]+>', '', abstract)
                    return abstract, "CrossRef"
                else:
                    return "No abstract available in CrossRef", "error"
                    
        except Exception as e:
            logger.error(f"CrossRef API error: {e}")
            return f"CrossRef API error: {str(e)}", "error"
    
    def reconstruct_abstract_from_inverted_index(self, inverted_index: dict) -> str:
        """Reconstruct abstract text from OpenAlex inverted index"""
        try:
            position_words = {}
            for word, positions in inverted_index.items():
                for pos in positions:
                    position_words[pos] = word
            
            sorted_positions = sorted(position_words.keys())
            abstract = ' '.join(position_words[pos] for pos in sorted_positions)
            
            return abstract
        except Exception as e:
            logger.error(f"Abstract reconstruction error: {e}")
            return ""
    
    async def get_abstract_multi_source(self, paper: dict) -> tuple[str, str]:
        """Get abstract using multiple sources with fallback mechanism"""
        title = paper.get('title', '')
        doi = paper.get('doi', '')
        pmid = paper.get('pmid', '')
        
        logger.debug(f"Fetching abstract for PMID {pmid}: {title[:50]}...")
        
        # Source priority: Semantic Scholar -> OpenAlex -> CrossRef
        sources = [
            ("Semantic Scholar", self.get_abstract_semantic_scholar, [title, doi]),
            ("OpenAlex", self.get_abstract_openalex, [title, doi]),
        ]
        
        # Add CrossRef if DOI is available
        if doi:
            sources.append(("CrossRef", self.get_abstract_crossref, [doi]))
        
        for source_name, func, args in sources:
            try:
                result, source = await func(*args)
                
                # Check if result is successful
                if source != "error":
                    logger.info(f"✅ Successfully got abstract from {source_name} for PMID {pmid}")
                    return result, source_name
                else:
                    logger.debug(f"❌ {source_name} failed for PMID {pmid}: {result}")
                    
            except Exception as e:
                logger.error(f"💥 {source_name} exception for PMID {pmid}: {e}")
                continue
        
        # If all sources fail
        return f"Failed to retrieve abstract from all sources for PMID {pmid}", "failed"

def create_paper_info(paper: Dict[str, Any], abstract: str = "", abstract_source: str = "") -> PaperInfo:
    """Create PaperInfo from PubTator3 API response data"""
    return PaperInfo(
        pmid=paper.get('pmid'),
        title=paper.get('title'),
        authors=paper.get('authors', []),
        journal=paper.get('journal'),
        date=paper.get('date'),
        doi=paper.get('doi'),
        abstract=abstract,
        abstract_source=abstract_source
    )

@mcp.tool(tags={"search", "academic", "public", "abstract"})
async def search_papers_by_abstract(
    query: str,
    page_size: int = 10,
    page: int = 1,
    include_full_abstracts: bool = True,
    max_concurrent: int = 3,
    ctx: Context = None
) -> dict:
    """
    Search for academic papers by abstract content using PubTator3 API.
    
    Args:
        query: Search query to find in paper abstracts
        page_size: Number of papers to return (max 50)
        page: Page number for pagination (starts from 1)
        include_full_abstracts: Whether to fetch full abstracts from multiple sources
        max_concurrent: Maximum concurrent API calls for fetching abstracts
    
    Returns:
        JSON response with paper information and abstracts
    """
    if ctx:
        await ctx.info(f"Searching papers by abstract content: {query}")
    
    if page_size > 50:
        page_size = 50
        if ctx:
            await ctx.warning("Page size limited to 50")
    
    try:
        client = await get_http_client()
        api = PubTator3API(client)
        
        # Step 1: Search papers by abstract using PubTator3
        search_results = await api.search_papers_by_abstract(
            query=query,
            page=page,
            page_size=page_size
        )
        
        papers = search_results.get("results", [])
        if not papers:
            return {
                "success": False,
                "query": query,
                "total_count": 0,
                "results": [],
                "error": "No papers found",
                "source": "pubtator3"
            }
        
        # Step 2: Get detailed abstracts if requested
        paper_infos = []
        if include_full_abstracts:
            if ctx:
                await ctx.info(f"Fetching full abstracts for {len(papers)} papers...")
            
            # Use semaphore to control concurrency
            semaphore = asyncio.Semaphore(max_concurrent)
            
            async def fetch_abstract_with_semaphore(paper):
                async with semaphore:
                    await asyncio.sleep(0.3)  # Rate limiting
                    return await api.get_abstract_multi_source(paper)
            
            # Fetch abstracts concurrently
            abstract_tasks = [fetch_abstract_with_semaphore(paper) for paper in papers]
            abstracts_results = await asyncio.gather(*abstract_tasks, return_exceptions=True)
            
            # Process results
            for paper, abstract_result in zip(papers, abstracts_results):
                if isinstance(abstract_result, Exception):
                    abstract_text = f"Error: {abstract_result}"
                    abstract_source = "error"
                    logger.error(f"Abstract fetch failed for PMID {paper['pmid']}: {abstract_result}")
                else:
                    abstract_text, abstract_source = abstract_result
                    
                paper_info = create_paper_info(paper, abstract_text, abstract_source)
                paper_infos.append(paper_info)
        else:
            # Create paper info without fetching full abstracts
            for paper in papers:
                paper_info = create_paper_info(paper)
                paper_infos.append(paper_info)
        
        # Create response
        response = PaperSearchResponse(
            success=True,
            query=query,
            total_count=len(papers),  # PubTator3 doesn't provide total count
            results=paper_infos
        )
        
        # Convert to dictionary for JSON serialization
        results_dict = []
        for paper in response.results:
            paper_dict = {
                "pmid": paper.pmid,
                "title": paper.title,
                "authors": paper.authors,
                "journal": paper.journal,
                "date": paper.date,
                "doi": paper.doi,
                "abstract": paper.abstract,
                "abstract_source": paper.abstract_source
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
        error_msg = f"PubTator3 Search Error: {str(e)}"
        if ctx:
            await ctx.error(error_msg)
        logger.error(f"Paper search failed: {str(e)}")
        return {
            "success": False,
            "query": query,
            "total_count": 0,
            "results": [],
            "source": "pubtator3",
            "error": error_msg
        }

# Custom HTTP endpoints
@mcp.custom_route("/api/search/abstract", methods=["POST"])
async def search_abstract_api(request: Request) -> JSONResponse:
    """Direct API endpoint for abstract-based paper search"""
    try:
        body = await request.json()
        query = body.get("query", "")
        page_size = body.get("page_size", 10)
        page = body.get("page", 1)
        include_full_abstracts = body.get("include_full_abstracts", True)
        
        if not query:
            return JSONResponse(
                {"error": "Query parameter is required"}, 
                status_code=400
            )
        
        result = await search_papers_by_abstract(
            query=query,
            page_size=page_size,
            page=page,
            include_full_abstracts=include_full_abstracts,
            ctx=None
        )
        
        return JSONResponse({
            "success": True,
            "query": query,
            "result": result,
            "endpoint": "custom_api",
            "tags_used": ["search", "academic", "abstract"]
        })
        
    except Exception as e:
        logger.error(f"Error in search_abstract_api: {e}")
        return JSONResponse(
            {"error": f"Search failed: {str(e)}"}, 
            status_code=500
        )

@mcp.custom_route("/api/health", methods=["GET"])
async def api_health_check(request: Request) -> JSONResponse:
    """API health check endpoint"""
    return JSONResponse({
        "status": "healthy",
        "service": "PubTator3 FastMCP Server",
        "version": "1.0.0",
        "features": [
            "Abstract-based paper search",
            "Multi-source abstract retrieval",
            "PubTator3 integration"
        ],
        "endpoints": {
            "mcp": "/mcp",
            "search_abstract": "/api/search/abstract",
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
        port = int(os.getenv("PORT", "8991"))
        logger.info(f"Starting PubTator3 FastMCP Server on HTTP transport at port {port}...")
        mcp.run(transport="http", host="0.0.0.0", port=port)
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        exit(1)