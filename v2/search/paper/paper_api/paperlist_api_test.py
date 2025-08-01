"""
Paperlist API Test - Async implementation with concurrent paper detail fetching
"""

import asyncio
import aiohttp
import logging
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PaperlistAPI:
    """Async client for Paperlist API"""
    
    BASE_URL = "https://www.papelist.app/api"
    
    def __init__(self, session: aiohttp.ClientSession = None):
        self.session = session
        self._owned_session = session is None
    
    async def __aenter__(self):
        if self._owned_session:
            self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._owned_session and self.session:
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
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Found {data.get('count', 0)} papers for query: {search_value}")
                    return data
                else:
                    raise Exception(f"Search API error: {response.status}")
        except Exception as e:
            logger.error(f"Failed to search papers: {e}")
            raise
    
    async def get_paper_detail(self, paper_id: int) -> Dict[str, Any]:
        """Get detailed information for a single paper"""
        
        url = f"{self.BASE_URL}/detail?id={paper_id}"
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.debug(f"Retrieved details for paper ID: {paper_id}")
                    return data
                else:
                    logger.warning(f"Detail API error for paper {paper_id}: {response.status}")
                    return {}
        except Exception as e:
            logger.error(f"Failed to get paper detail for ID {paper_id}: {e}")
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
                return await self.get_paper_detail(paper_id)
        
        tasks = [fetch_detail(paper_id) for paper_id in paper_ids]
        results = await asyncio.gather(*tasks)
        
        logger.info(f"Retrieved details for {len([r for r in results if r])} papers")
        return results


async def search_and_get_details(
    search_query: str,
    page_size: int = 20,
    max_concurrent: int = 10
) -> List[Dict[str, Any]]:
    """Search papers and get their detailed information including abstracts"""
    
    async with PaperlistAPI() as api:
        # Step 1: Search for papers
        logger.info(f"Searching for papers with query: {search_query}")
        search_results = await api.search_papers(
            search_value=search_query,
            page_size=page_size
        )
        
        papers = search_results.get("page", [])
        if not papers:
            logger.warning("No papers found")
            return []
        
        # Extract paper IDs
        paper_ids = [paper["id"] for paper in papers]
        logger.info(f"Found {len(paper_ids)} papers, fetching details...")
        
        # Step 2: Get detailed information concurrently
        details = await api.get_papers_details_concurrent(
            paper_ids, 
            max_concurrent=max_concurrent
        )
        
        # Step 3: Combine search results with details
        enriched_papers = []
        for paper, detail in zip(papers, details):
            arxiv_id = detail.get("id_arxiv", "")
            enriched_paper = {
                **paper,
                "abstract": detail.get("abstr", ""),
                "doi": detail.get("id_doi", ""),
                "arxiv_id": arxiv_id,
                "arxiv_pdf_url": f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
                "semantic_scholar_id": detail.get("id_s2", ""),
                "dblp_id": detail.get("id_dblp", ""),
                "pubmed_id": detail.get("id_pm", ""),
                "pmc_id": detail.get("id_pmc", "")
            }
            enriched_papers.append(enriched_paper)
        
        return enriched_papers


async def main():
    """Main function to demonstrate the API usage"""
    
    # Test with LLM search
    search_queries = ["LLM", "machine learning", "neural networks"]
    
    for query in search_queries:
        logger.info(f"\n{'='*50}")
        logger.info(f"Testing query: {query}")
        logger.info(f"{'='*50}")
        
        try:
            papers = await search_and_get_details(
                search_query=query,
                page_size=5,  # Limit for demo
                max_concurrent=5
            )
            
            # Display results
            for i, paper in enumerate(papers, 1):
                logger.info(f"\n{i}. {paper['title']}")
                logger.info(f"   Authors: {paper['authors']}")
                logger.info(f"   Year: {paper['year']}")
                logger.info(f"   Citations: {paper['cits_n']}")
                
                abstract = paper.get('abstract', '')
                if abstract:
                    logger.info(f"   Abstract: {abstract[:200]}...")
                else:
                    logger.info("   Abstract: Not available")
                
                if paper.get('arxiv_id'):
                    logger.info(f"   ArXiv: https://arxiv.org/abs/{paper['arxiv_id']}")
                    logger.info(f"   ArXiv PDF: {paper.get('arxiv_pdf_url', '')}")
                if paper.get('doi'):
                    logger.info(f"   DOI: https://doi.org/{paper['doi']}")
        
        except Exception as e:
            logger.error(f"Error processing query '{query}': {e}")


if __name__ == "__main__":
    asyncio.run(main())