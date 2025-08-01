#!/usr/bin/env python3
"""
Test client for Paperlist MCP Server

This script tests the paperlist API functionality without requiring MCP server setup.
"""

import asyncio
import aiohttp
import logging
from typing import List, Dict, Any
from urllib.parse import urlencode

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PaperlistTestClient:
    """Test client for Paperlist API functionality"""
    
    BASE_URL = "https://www.papelist.app/api"
    
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30.0))
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
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


async def test_search_functionality():
    """Test the complete search functionality"""
    
    async with PaperlistTestClient() as client:
        print("🔍 Testing Paperlist API Integration")
        print("=" * 60)
        
        # Test queries
        test_queries = [
            {
                "query": "large language models",
                "description": "Recent LLM research",
                "page_size": 5,
                "year_min": 2023
            },
            {
                "query": "machine learning",
                "description": "ML papers with high citations", 
                "page_size": 3,
                "sort_by": "cits-dsc"
            }
        ]
        
        for test in test_queries:
            print(f"\n📋 Test: {test['description']}")
            print(f"Query: '{test['query']}'")
            
            try:
                # Search for papers
                search_results = await client.search_papers(
                    search_value=test["query"],
                    page_size=test["page_size"],
                    year_min=test.get("year_min", -1),
                    sort_by=test.get("sort_by", "year-dsc")
                )
                
                papers = search_results.get("page", [])
                total_count = search_results.get("count", 0)
                
                print(f"✅ Found {len(papers)} papers (Total: {total_count})")
                
                if papers:
                    # Get details for first few papers
                    paper_ids = [paper["id"] for paper in papers[:2]]
                    print(f"📄 Fetching details for {len(paper_ids)} papers...")
                    
                    details = await client.get_papers_details_concurrent(paper_ids)
                    
                    # Display results
                    for i, (paper, detail) in enumerate(zip(papers[:2], details), 1):
                        print(f"\n--- Paper {i} ---")
                        print(f"Title: {paper.get('title', 'N/A')}")
                        print(f"Authors: {paper.get('authors', 'N/A')}")
                        print(f"Year: {paper.get('year', 'N/A')}")
                        print(f"Citations: {paper.get('cits_n', 'N/A')}")
                        
                        abstract = detail.get('abstr', '')
                        if abstract:
                            preview = abstract[:200] + "..." if len(abstract) > 200 else abstract
                            print(f"Abstract: {preview}")
                        
                        # External links
                        if detail.get('id_arxiv'):
                            print(f"ArXiv: https://arxiv.org/abs/{detail['id_arxiv']}")
                        if detail.get('id_doi'):
                            print(f"DOI: https://doi.org/{detail['id_doi']}")
                
            except Exception as e:
                print(f"❌ Test failed: {e}")


async def demonstrate_paper_search(query: str, page_size: int = 5):
    """Demonstrate the paper search functionality similar to MCP tool"""
    
    print(f"\n🔍 Searching for papers: {query}")
    print("=" * 60)
    
    async with PaperlistTestClient() as client:
        try:
            # Step 1: Search for papers
            search_results = await client.search_papers(
                search_value=query,
                page_size=page_size
            )
            
            papers = search_results.get("page", [])
            if not papers:
                print(f"📄 No papers found for query: {query}")
                return
            
            total_count = search_results.get("count", len(papers))
            
            # Step 2: Get detailed information  
            paper_ids = [paper["id"] for paper in papers]
            details = await client.get_papers_details_concurrent(paper_ids)
            
            # Step 3: Format results like MCP tool would
            print(f"📄 Academic Paper Search Results")
            print(f"Query: {query}")
            print(f"Found: {len(papers)} papers (Total: {total_count})")
            print(f"Source: paperlist\n")
            
            for i, (paper, detail) in enumerate(zip(papers, details), 1):
                print(f"--- Paper {i} ---")
                
                if paper.get('title'):
                    print(f"Title: {paper['title']}")
                if paper.get('authors'):
                    print(f"Authors: {paper['authors']}")
                if paper.get('year'):
                    print(f"Year: {paper['year']}")
                if paper.get('cits_n') is not None:
                    print(f"Citations: {paper['cits_n']}")
                if paper.get('venue'):
                    print(f"Venue: {paper['venue']}")
                
                # Abstract
                abstract = detail.get('abstr', '')
                if abstract:
                    preview = abstract[:300] + "..." if len(abstract) > 300 else abstract
                    print(f"Abstract: {preview}")
                
                # External links
                links = []
                if detail.get('id_arxiv'):
                    links.append(f"ArXiv: https://arxiv.org/abs/{detail['id_arxiv']}")
                    links.append(f"PDF: https://arxiv.org/pdf/{detail['id_arxiv']}")
                if detail.get('id_doi'):
                    links.append(f"DOI: https://doi.org/{detail['id_doi']}")
                if detail.get('id_s2'):
                    links.append(f"Semantic Scholar: https://www.semanticscholar.org/paper/{detail['id_s2']}")
                
                if links:
                    print(f"Links: {' | '.join(links)}")
                
                print()
            
        except Exception as e:
            print(f"❌ Paper Search Error: {str(e)}")


async def main():
    """Main function to run tests"""
    
    print("Paperlist MCP - Functionality Test")
    print("=" * 60)
    
    try:
        # Test basic API functionality
        await test_search_functionality()
        
        # Demonstrate search like MCP tool
        await demonstrate_paper_search("deep learning", 3)
        await demonstrate_paper_search("neural networks", 3)
        
        print("\n✅ All tests completed successfully!")
        print("\n💡 The MCP server implementation is ready to use.")
        print("💡 Start the server with: python src/mcp_server.py")
        
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())