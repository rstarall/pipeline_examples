"""
1.根据摘要内关键词进行搜索:
https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/?text=abstract:"machine learning"&page=1
https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/?text=abstract:"deep learning" AND abstract:"medical imaging"&page=1
"""
"""
2.获取摘要 - 使用多个API源获得更高成功率
"""
import asyncio
import aiohttp
from typing import List, Dict, Any
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def get_abstract_semantic_scholar(session: aiohttp.ClientSession, title: str, doi: str = None) -> str:
    """Get abstract from Semantic Scholar API - 最可靠的摘要来源"""
    try:
        # Try DOI first if available
        if doi:
            search_query = f'doi:"{doi}"'
        else:
            # Use title search as fallback
            search_query = title.replace('"', '\\"')
        
        url = "https://api.semanticscholar.org/graph/v1/paper/search"
        params = {
            'query': search_query,
            'limit': 1,
            'fields': 'abstract,title,doi'
        }
        headers = {'Accept': 'application/json'}
        
        async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status != 200:
                return f"Semantic Scholar API error: {response.status}"
                
            data = await response.json()
            
            if data.get('total', 0) > 0 and data.get('data'):
                paper = data['data'][0]
                abstract = paper.get('abstract', '').strip()
                
                if abstract:
                    return abstract
                else:
                    return "No abstract available in Semantic Scholar"
            else:
                return "Paper not found in Semantic Scholar"
                
    except Exception as e:
        logger.error(f"Semantic Scholar API error: {e}")
        return f"Semantic Scholar API error: {str(e)}"


async def get_abstract_openalex(session: aiohttp.ClientSession, title: str, doi: str = None) -> str:
    """Get abstract from OpenAlex API - 开放学术数据库"""
    try:
        # Construct search URL
        url = "https://api.openalex.org/works"
        
        # Try DOI first if available
        if doi:
            params = {
                'filter': f'doi:{doi}',
                'select': 'abstract_inverted_index,title,doi'
            }
        else:
            # Use title search as fallback
            params = {
                'search': title,
                'select': 'abstract_inverted_index,title,doi',
                'per_page': 1
            }
        
        headers = {'Accept': 'application/json', 'User-Agent': 'PaperSearchBot/1.0'}
        
        async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status != 200:
                return f"OpenAlex API error: {response.status}"
                
            data = await response.json()
            
            if data.get('results'):
                paper = data['results'][0]
                abstract_inverted = paper.get('abstract_inverted_index')
                
                if abstract_inverted:
                    # Reconstruct abstract from inverted index
                    abstract = reconstruct_abstract_from_inverted_index(abstract_inverted)
                    return abstract if abstract else "Abstract reconstruction failed"
                else:
                    return "No abstract available in OpenAlex"
            else:
                return "Paper not found in OpenAlex"
                
    except Exception as e:
        logger.error(f"OpenAlex API error: {e}")
        return f"OpenAlex API error: {str(e)}"


def reconstruct_abstract_from_inverted_index(inverted_index: dict) -> str:
    """Reconstruct abstract text from OpenAlex inverted index"""
    try:
        # Create position->word mapping
        position_words = {}
        for word, positions in inverted_index.items():
            for pos in positions:
                position_words[pos] = word
        
        # Sort by position and join
        sorted_positions = sorted(position_words.keys())
        abstract = ' '.join(position_words[pos] for pos in sorted_positions)
        
        return abstract
    except Exception as e:
        logger.error(f"Abstract reconstruction error: {e}")
        return ""


async def get_abstract_crossref(session: aiohttp.ClientSession, doi: str) -> str:
    """Get abstract from CrossRef API - DOI必需"""
    if not doi:
        return "DOI required for CrossRef"
    
    try:
        url = f"https://api.crossref.org/works/{doi}"
        headers = {'Accept': 'application/json', 'User-Agent': 'PaperSearchBot/1.0'}
        
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status != 200:
                return f"CrossRef API error: {response.status}"
                
            data = await response.json()
            message = data.get('message', {})
            abstract = message.get('abstract', '').strip()
            
            if abstract:
                # Remove HTML tags if present
                import re
                abstract = re.sub(r'<[^>]+>', '', abstract)
                return abstract
            else:
                return "No abstract available in CrossRef"
                
    except Exception as e:
        logger.error(f"CrossRef API error: {e}")
        return f"CrossRef API error: {str(e)}"


async def get_abstract_multi_source(session: aiohttp.ClientSession, paper: dict) -> str:
    """Get abstract using multiple sources with fallback mechanism"""
    title = paper.get('title', '')
    doi = paper.get('doi', '')
    pmid = paper.get('pmid', '')
    
    logger.debug(f"Fetching abstract for: {title[:50]}...")
    
    # Source priority: Semantic Scholar -> OpenAlex -> CrossRef
    sources = [
        ("Semantic Scholar", get_abstract_semantic_scholar, [title, doi]),
        ("OpenAlex", get_abstract_openalex, [title, doi]),
    ]
    
    # Add CrossRef if DOI is available
    if doi:
        sources.append(("CrossRef", get_abstract_crossref, [doi]))
    
    for source_name, func, args in sources:
        try:
            result = await func(session, *args)
            
            # Check if result is successful (not an error message)
            if not any(error_indicator in result.lower() for error_indicator in 
                      ['error', 'not found', 'failed', 'no abstract available']):
                logger.info(f"✅ Successfully got abstract from {source_name} for PMID {pmid}")
                return f"[{source_name}] {result}"
            else:
                logger.debug(f"❌ {source_name} failed for PMID {pmid}: {result}")
                
        except Exception as e:
            logger.error(f"💥 {source_name} exception for PMID {pmid}: {e}")
            continue
    
    # If all sources fail, return a consolidated error message
    return f"Failed to retrieve abstract from all sources for PMID {pmid}"


async def get_paper_details(search_query: str, page: int = 1, page_size: int = 10) -> List[Dict[Any, Any]]:
    """Complete paper search and abstract retrieval with multi-source async concurrency"""
    
    # 1. Search papers using PubTator3
    search_url = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api/search/"
    search_params = {
        'text': f'abstract:"{search_query}"',
        'page_size': page_size,
        'page': page
    }
    
    # Configure session with proper headers and connection limits
    connector = aiohttp.TCPConnector(
        limit=10,  # Increase limit for multiple APIs
        limit_per_host=5,  # Allow more connections per host
        ttl_dns_cache=300,
        use_dns_cache=True,
    )
    
    headers = {
        'User-Agent': 'PaperSearchBot/1.0 (research@example.com)',
        'Accept': 'application/json',
        'Connection': 'keep-alive'
    }
    
    timeout = aiohttp.ClientTimeout(total=60, connect=10)
    
    async with aiohttp.ClientSession(
        connector=connector, 
        headers=headers, 
        timeout=timeout
    ) as session:
        try:
            async with session.get(search_url, params=search_params) as response:
                search_data = await response.json()
                papers = search_data['results']
                
            logger.info(f"Found {len(papers)} papers for query: {search_query}")
            
            # 2. Fetch abstracts using multiple sources with controlled concurrency
            semaphore = asyncio.Semaphore(3)  # Limit to 3 concurrent requests
            
            async def fetch_with_semaphore(paper):
                async with semaphore:
                    # Add small delay between requests
                    await asyncio.sleep(0.3)
                    return await get_abstract_multi_source(session, paper)
            
            abstract_tasks = []
            for paper in papers:
                task = fetch_with_semaphore(paper)
                abstract_tasks.append(task)
            
            # Execute abstract fetches with controlled concurrency
            logger.info(f"🚀 Starting to fetch abstracts for {len(abstract_tasks)} papers using multiple APIs...")
            abstracts = await asyncio.gather(*abstract_tasks, return_exceptions=True)
            logger.info("✅ Finished fetching all abstracts")
            
            # 3. Process and display results
            for i, (paper, abstract) in enumerate(zip(papers, abstracts)):
                # Handle exceptions
                if isinstance(abstract, Exception):
                    abstract_text = f"Error: {abstract}"
                    logger.error(f"Abstract fetch failed for PMID {paper['pmid']}: {abstract}")
                else:
                    abstract_text = abstract
                    
                paper['abstract'] = abstract_text
                
                # Output paper information immediately
                print(f"\n--- Paper {i+1}/{len(papers)} ---")
                print(f"PMID: {paper['pmid']}")
                print(f"Title: {paper['title']}")
                print(f"Journal: {paper['journal']}")
                print(f"Date: {paper['date']}")
                print(f"Authors: {', '.join(paper['authors'])}")
                print(f"DOI: {paper.get('doi', 'N/A')}")
                
                # Display abstract with length info and source
                if abstract_text.startswith("Error:") or "Failed to retrieve" in abstract_text:
                    print(f"Abstract: ❌ {abstract_text}")
                else:
                    print(f"Abstract: ✅ {abstract_text}")
                    
                print("-" * 80)
            
            return papers
            
        except Exception as e:
            logger.error(f"Error in paper search and retrieval: {e}")
            raise


async def main():
    """Main function to run the paper search"""
    try:
        search_query = "deep learning"
        page_size = 5
        
        logger.info(f"🔍 Starting paper search for query: '{search_query}'")
        papers = await get_paper_details(search_query, page=1, page_size=page_size)
        
        # Generate summary statistics
        total_papers = len(papers)
        successful_abstracts = sum(1 for paper in papers 
                                 if not any(x in paper['abstract'] for x in ['Error:', 'Failed to retrieve']))
        failed_abstracts = total_papers - successful_abstracts
        
        # Count source statistics
        source_stats = {}
        for paper in papers:
            abstract = paper['abstract']
            if abstract.startswith('[') and ']' in abstract:
                source = abstract.split(']')[0][1:]
                source_stats[source] = source_stats.get(source, 0) + 1
        
        print(f"\n{'='*60}")
        print("📊 SEARCH SUMMARY")
        print(f"{'='*60}")
        print(f"Query: {search_query}")
        print(f"Total papers found: {total_papers}")
        print(f"Abstracts successfully retrieved: {successful_abstracts}")
        print(f"Abstracts failed to retrieve: {failed_abstracts}")
        print(f"Success rate: {(successful_abstracts/total_papers*100):.1f}%" if total_papers > 0 else "N/A")
        
        if source_stats:
            print("\n📈 Source Statistics:")
            for source, count in source_stats.items():
                print(f"  {source}: {count} abstracts")
        
        print(f"{'='*60}")
        
        logger.info(f"Search completed: {successful_abstracts}/{total_papers} abstracts retrieved successfully")
        
    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())