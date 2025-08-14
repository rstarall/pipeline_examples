#!/usr/bin/env python3
"""
Semantic Scholar FastMCP Server with PDF Download and Text Extraction

A FastMCP server providing academic paper search capabilities
using Semantic Scholar API with PDF download and text extraction functionality.
"""

import asyncio
import logging
import json
import os
import re
import tempfile
from typing import Any, Dict, List, Optional
from datetime import datetime
from urllib.parse import urljoin, urlparse

import aiohttp
import aiofiles
from pydantic import BaseModel
from fastmcp import FastMCP, Context
from starlette.requests import Request
from starlette.responses import JSONResponse
from bs4 import BeautifulSoup

# PDF processing imports
try:
    import PyPDF2
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError as e:
    logging.warning(f"PDF processing libraries not available: {e}")
    PDF_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Semantic Scholar API configuration
SEMANTIC_SCHOLAR_API_KEY = "8Bbu1DtnaZ6BydBaYeiPj8ye5KSMynoU1lk2zyLn"
SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

# PDF download configuration
SCI_HUB_BASE_URL = "https://sci-hub.vkif.top/"
MAX_PDF_SIZE = 50 * 1024 * 1024  # 50MB limit

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
    # New fields for PDF content
    pdf_text: Optional[str] = None
    pdf_download_url: Optional[str] = None
    pdf_source: Optional[str] = None  # 'open_access', 'sci_hub', or None

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
            'X-API-KEY': SEMANTIC_SCHOLAR_API_KEY,
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

async def extract_pdf_links_from_page(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """Extract PDF download links from paper page - any href ending with .pdf"""
    try:
        async with session.get(url) as response:
            if response.status != 200:
                return None
            
            html_content = await response.text()
            
            # Look for any PDF links - more flexible pattern
            pdf_pattern = r'href="([^"]*\.pdf)"'
            matches = re.findall(pdf_pattern, html_content)
            
            if matches:
                # Get the base URL
                parsed_url = urlparse(url)
                base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
                
                # Return the first PDF link found, handle relative URLs
                pdf_path = matches[0]
                if pdf_path.startswith('http'):
                    return pdf_path  # Absolute URL
                else:
                    return urljoin(base_url, pdf_path)  # Relative URL
                
    except Exception as e:
        logger.error(f"Error extracting PDF links from {url}: {str(e)}")
    
    return None

async def download_pdf_from_scihub(session: aiohttp.ClientSession, doi: str) -> Optional[bytes]:
    """Download PDF from sci-hub using DOI"""
    if not doi:
        return None
    
    try:
        # Construct sci-hub URL
        scihub_url = f"{SCI_HUB_BASE_URL}{doi}"
        
        async with session.get(scihub_url) as response:
            if response.status != 200:
                logger.warning(f"Sci-hub returned status {response.status} for DOI: {doi}")
                return None
            
            html_content = await response.text()
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Look for PDF download link
            pdf_link = None
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '.pdf' in href and ('sci-hub' in href or href.startswith('/')):
                    if href.startswith('/'):
                        pdf_link = urljoin(SCI_HUB_BASE_URL, href)
                    else:
                        pdf_link = href
                    break
            
            if not pdf_link:
                # Try alternative approach - look for embed or iframe
                for embed in soup.find_all(['embed', 'iframe']):
                    src = embed.get('src', '')
                    if '.pdf' in src:
                        if src.startswith('/'):
                            pdf_link = urljoin(SCI_HUB_BASE_URL, src)
                        else:
                            pdf_link = src
                        break
            
            if pdf_link:
                # Download the actual PDF
                async with session.get(pdf_link) as pdf_response:
                    if pdf_response.status == 200:
                        content_length = pdf_response.headers.get('content-length')
                        if content_length and int(content_length) > MAX_PDF_SIZE:
                            logger.warning(f"PDF too large: {content_length} bytes")
                            return None
                        
                        pdf_data = await pdf_response.read()
                        if len(pdf_data) > 1000:  # Basic sanity check
                            return pdf_data
                            
    except Exception as e:
        logger.error(f"Error downloading from sci-hub for DOI {doi}: {str(e)}")
    
    return None

async def download_pdf(session: aiohttp.ClientSession, url: str) -> Optional[bytes]:
    """Download PDF from direct URL"""
    try:
        async with session.get(url) as response:
            if response.status != 200:
                return None
            
            content_length = response.headers.get('content-length')
            if content_length and int(content_length) > MAX_PDF_SIZE:
                logger.warning(f"PDF too large: {content_length} bytes")
                return None
            
            pdf_data = await response.read()
            
            # Basic PDF validation
            if pdf_data.startswith(b'%PDF'):
                return pdf_data
                
    except Exception as e:
        logger.error(f"Error downloading PDF from {url}: {str(e)}")
    
    return None

async def extract_text_from_pdf(pdf_data: bytes) -> Optional[str]:
    """Extract text from PDF data"""
    if not PDF_AVAILABLE or not pdf_data:
        return None
    
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as temp_file:
            temp_file.write(pdf_data)
            temp_path = temp_file.name
        
        try:
            # Try pdfplumber first (better for complex layouts)
            with pdfplumber.open(temp_path) as pdf:
                text_parts = []
                for page in pdf.pages[:10]:  # Limit to first 10 pages
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                
                if text_parts:
                    full_text = '\n\n'.join(text_parts)
                    return full_text[:10000]  # Limit to 10k characters
            
            # Fallback to PyPDF2
            with open(temp_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text_parts = []
                
                for page_num in range(min(10, len(pdf_reader.pages))):
                    page = pdf_reader.pages[page_num]
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                
                if text_parts:
                    full_text = '\n\n'.join(text_parts)
                    return full_text[:10000]  # Limit to 10k characters
                    
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except:
                pass
                
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {str(e)}")
    
    return None

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
                SEMANTIC_SCHOLAR_URL,
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

    async def parse_paper_info(self, paper_data: Dict[str, Any], enable_pdf_download: bool = True) -> PaperInfo:
        """Parse paper data from API response into PaperInfo model with PDF processing"""
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
            
            # Try to download and extract PDF text
            pdf_text = None
            pdf_download_url = None
            pdf_source = None
            
            if enable_pdf_download:
                try:
                    # First try open access PDF - check if URL ends with .pdf
                    if open_access_pdf and open_access_pdf.url:
                        if open_access_pdf.url.lower().endswith('.pdf'):
                            logger.info(f"Attempting to download open access PDF (direct): {open_access_pdf.url}")
                            pdf_data = await download_pdf(self.session, open_access_pdf.url)
                            if pdf_data:
                                pdf_text = await extract_text_from_pdf(pdf_data)
                                pdf_download_url = open_access_pdf.url
                                pdf_source = "open_access"
                                logger.info(f"Successfully extracted text from open access PDF")
                        else:
                            logger.info(f"Open access PDF URL doesn't end with .pdf, skipping: {open_access_pdf.url}")
                    
                    # If no open access PDF, try to extract from paper page
                    if not pdf_text and paper_data.get('url'):
                        logger.info(f"Attempting to extract PDF link from page: {paper_data.get('url')}")
                        extracted_pdf_url = await extract_pdf_links_from_page(self.session, paper_data.get('url'))
                        if extracted_pdf_url:
                            pdf_data = await download_pdf(self.session, extracted_pdf_url)
                            if pdf_data:
                                pdf_text = await extract_text_from_pdf(pdf_data)
                                pdf_download_url = extracted_pdf_url
                                pdf_source = "open_access"
                                logger.info(f"Successfully extracted text from extracted PDF link")
                    
                    # If still no PDF and we have DOI, try sci-hub (for papers before 2022)
                    year = paper_data.get('year')
                    doi = external_ids.DOI if external_ids else None
                    if not pdf_text and doi and year and year < 2022:
                        logger.info(f"Attempting to download from sci-hub for DOI: {doi}")
                        pdf_data = await download_pdf_from_scihub(self.session, doi)
                        if pdf_data:
                            pdf_text = await extract_text_from_pdf(pdf_data)
                            pdf_download_url = f"{SCI_HUB_BASE_URL}{doi}"
                            pdf_source = "sci_hub"
                            logger.info(f"Successfully extracted text from sci-hub PDF")
                    
                except Exception as pdf_error:
                    logger.error(f"Error processing PDF for paper {paper_data.get('paperId')}: {str(pdf_error)}")
            
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
                authors=authors,
                pdf_text=pdf_text,
                pdf_download_url=pdf_download_url,
                pdf_source=pdf_source
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
    enable_pdf_download: bool = True,
    ctx: Context = None
) -> Dict[str, Any]:
    """Search for academic papers using Semantic Scholar API
    
    Args:
        query: The search query string
        limit: Maximum number of results to return (default: 10, max: 100)
        offset: Number of results to skip for pagination (default: 0)
        enable_pdf_download: Whether to download and extract PDF text (default: True)
        
    Returns:
        Dictionary containing search results with paper information and optional PDF text
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
            paper = await api.parse_paper_info(paper_data, enable_pdf_download)
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
                "authors": [author.dict() for author in paper.authors] if paper.authors else [],
                "pdf_text": paper.pdf_text,
                "pdf_download_url": paper.pdf_download_url,
                "pdf_source": paper.pdf_source
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
        enable_pdf_download = body.get("enable_pdf_download", True)
        
        if not query:
            return JSONResponse(
                {"error": "Query parameter is required"}, 
                status_code=400
            )
        
        result = await search_papers(
            query=query,
            limit=limit,
            offset=offset,
            enable_pdf_download=enable_pdf_download,
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
        "service": "Semantic Scholar FastMCP Server with PDF Processing",
        "version": "2.0.0",
        "api_key_configured": bool(SEMANTIC_SCHOLAR_API_KEY),
        "pdf_processing_available": PDF_AVAILABLE,
        "features": [
            "Academic paper search",
            "Semantic Scholar API integration",
            "Comprehensive paper metadata",
            "PDF download and text extraction",
            "Open access PDF support",
            "Sci-hub integration for older papers",
            "Regex-based PDF link extraction"
        ],
        "endpoints": {
            "mcp": "/mcp",
            "search_papers": "/api/search/papers",
            "health": "/api/health"
        },
        "pdf_sources": [
            "open_access",
            "sci_hub"
        ]
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
        port = int(os.getenv("PORT", "8993"))
        logger.info(f"Starting Semantic Scholar FastMCP Server with PDF Download and Text Extraction on HTTP transport at port {port}...")
        logger.info(f"API Key configured: {bool(SEMANTIC_SCHOLAR_API_KEY)}")
        logger.info(f"PDF processing available: {PDF_AVAILABLE}")
        mcp.run(transport="http", host="0.0.0.0", port=port)
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server failed to start: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        exit(1)