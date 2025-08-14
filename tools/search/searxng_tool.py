"""
title: SearxNG Web Search Tool
author: Assistant
version: 1.0
license: MIT
description: A tool for web search using SearxNG search engine
"""

import json
import requests
import asyncio
import aiohttp
from typing import Callable, Any, Optional, List, Dict
from pydantic import BaseModel, Field

EmitterType = Optional[Callable[[dict], Any]]


class EventEmitter:
    def __init__(self, event_emitter: EmitterType):
        self.event_emitter = event_emitter

    async def emit(self, event_type: str, data: dict):
        if self.event_emitter:
            await self.event_emitter({"type": event_type, "data": data})

    async def update_status(
        self, description: str, done: bool, action: str, urls: List[str] = None
    ):
        await self.emit(
            "status",
            {"done": done, "action": action, "description": description, "urls": urls or []},
        )

    async def send_citation(self, title: str, url: str, content: str):
        await self.emit(
            "citation",
            {
                "document": [content],
                "metadata": [{"name": title, "source": url, "html": False}],
            },
        )


class Tools:
    def __init__(self):
        self.valves = self.Valves()
        
    class Valves(BaseModel):
        SEARXNG_URL: str = Field(
            default="http://43.154.132.202:8081",
            description="SearxNG服务器地址/SearxNG server URL",
        )
        SEARXNG_TIMEOUT: int = Field(
            default=15,
            description="搜索请求超时时间（秒）/Search request timeout in seconds",
        )
        SEARXNG_LANGUAGE: str = Field(
            default="zh-CN",
            description="搜索语言/Search language (e.g., zh-CN, en-US)",
        )
        SEARXNG_SAFESEARCH: int = Field(
            default=0,
            description="安全搜索级别/Safe search level (0=off, 1=moderate, 2=strict)",
        )
        SEARXNG_CATEGORIES: str = Field(
            default="general",
            description="搜索分类/Search categories (e.g., general, news, images)",
        )
        SEARXNG_TIME_RANGE: str = Field(
            default="",
            description="时间范围/Time range (e.g., day, week, month, year)",
        )
        DEFAULT_SEARCH_COUNT: int = Field(
            default=15,
            description="默认搜索结果数量/Default number of search results",
        )
        MAX_SEARCH_COUNT: int = Field(
            default=50,
            description="最大搜索结果数量限制/Maximum limit for search results",
        )
        CONTENT_EXTRACT_URL: str = Field(
            default="http://43.154.132.202:8082/extract",
            description="网页内容提取服务地址/Web content extraction service URL",
        )
        CONTENT_EXTRACT_TIMEOUT: int = Field(
            default=10,
            description="网页内容提取超时时间（秒）/Content extraction timeout in seconds",
        )
        ENABLE_CONTENT_EXTRACTION: bool = Field(
            default=True,
            description="是否启用网页内容提取/Enable web content extraction",
        )

    def _identify_website_type(self, url: str) -> str:
        """识别网站类型"""
        url_lower = url.lower()
        
        if 'wikipedia' in url_lower:
            return 'wiki'
        elif 'baike.baidu' in url_lower:
            return '百度百科'
        elif 'wiki.mbalib' in url_lower:
            return 'MBA智库百科'
        elif any(keyword in url_lower for keyword in ['arxiv', 'doi', '.pdf']):
            return '论文'
        elif any(keyword in url_lower for keyword in ['blog', 'csdn', 'cnblogs', 'jianshu', 'zhihu', 'segmentfault']):
            return '博客'
        elif any(keyword in url_lower for keyword in ['github', 'stackoverflow', 'medium']):
            return '技术文档'
        else:
            return '其他'

    async def _extract_content(self, session, url: str) -> dict:
        """异步提取网页内容"""
        try:
            payload = {"url": url}
            async with session.post(
                self.valves.CONTENT_EXTRACT_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.valves.CONTENT_EXTRACT_TIMEOUT)
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return {
                        "url": url,
                        "success": result.get("success", False),
                        "title": result.get("title", ""),
                        "content": result.get("content", ""),
                        "extracted_at": result.get("extracted_at", 0),
                        "error": result.get("error")
                    }
                else:
                    return {
                        "url": url,
                        "success": False,
                        "title": "",
                        "content": "",
                        "extracted_at": 0,
                        "error": f"HTTP {response.status}"
                    }
        except Exception as e:
            return {
                "url": url,
                "success": False,
                "title": "",
                "content": "",
                "extracted_at": 0,
                "error": str(e)
            }

    async def _extract_contents_batch(self, urls: List[str]) -> List[dict]:
        """批量异步提取网页内容"""
        if not self.valves.ENABLE_CONTENT_EXTRACTION or not urls:
            return []
        
        async with aiohttp.ClientSession() as session:
            tasks = [self._extract_content(session, url) for url in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理异常结果
            processed_results = []
            for i, result in enumerate(results):
                if isinstance(result, dict):
                    processed_results.append(result)
                else:
                    # 处理异常情况
                    processed_results.append({
                        "url": urls[i] if i < len(urls) else "",
                        "success": False,
                        "title": "",
                        "content": "",
                        "extracted_at": 0,
                        "error": str(result)
                    })
            
            return processed_results

    async def search_web(
        self,
        query: str = Field(..., description="The query for web search, Understand the user's question based on context and provide appropriate keywords for search. Extract core concepts and keywords, avoid redundant words, ensure the search query is concise and precise. "),
        limit: Optional[int] = None,
        language: Optional[str] = None,
        categories: Optional[str] = None,
        time_range: Optional[str] = None,
        safesearch: Optional[int] = None,
        __event_emitter__: EmitterType = None
    ) -> str:
        """
        Search the web using SearxNG search engine. This tool performs web searches and returns
        relevant results including titles, URLs, snippets, and website types.
        
        Use this tool when users ask about:
        - General web search queries
        - Current information and news
        - Website content and resources
        - Product information and reviews
        - Technical documentation and tutorials
        - Any topic that requires web search results
        
        The tool supports various search parameters including language, categories, time range,
        and safe search settings for customized search results.

        :param query: The query for web search, Understand the user's question based on context and provide appropriate keywords for search 
        :param limit: Maximum number of search results to return (default: configured default, max: configured max)
        :param language: Search language (default: configured language, e.g., "zh-CN", "en-US")
        :param categories: Search categories (default: "general", options: "general", "news", "images", etc.)
        :param time_range: Time range for search results (options: "day", "week", "month", "year")
        :param safesearch: Safe search level (0=off, 1=moderate, 2=strict)
        :param __event_emitter__: Optional event emitter for status updates
        :return: JSON formatted search results containing web page details
        """
        emitter = EventEmitter(__event_emitter__)
        
        # 验证参数
        if not query or not query.strip():
            await emitter.update_status("搜索查询不能为空", True, "web_search")
            return json.dumps({"error": "搜索查询不能为空", "success": False}, ensure_ascii=False, indent=2)
        
        # 设置默认值和限制
        if limit is None:
            limit = self.valves.DEFAULT_SEARCH_COUNT
        limit = min(limit, self.valves.MAX_SEARCH_COUNT)
        
        if language is None:
            language = self.valves.SEARXNG_LANGUAGE
        if categories is None:
            categories = self.valves.SEARXNG_CATEGORIES
        if time_range is None:
            time_range = self.valves.SEARXNG_TIME_RANGE
        if safesearch is None:
            safesearch = self.valves.SEARXNG_SAFESEARCH
        
        await emitter.update_status(
            f"正在搜索网页: {query} (限制: {limit}个结果)",
            False,
            "web_search"
        )
        
        try:
            # 构建SearxNG API请求
            url = f"{self.valves.SEARXNG_URL.strip().rstrip('/')}/search"
            
            params = {
                'q': query.strip(),
                'format': 'json',
                'language': language,
                'safesearch': safesearch,
                'categories': categories
            }
            
            if time_range:
                params['time_range'] = time_range
            
            # 发送搜索请求
            response = requests.get(
                url,
                params=params,
                timeout=self.valves.SEARXNG_TIMEOUT
            )
            response.raise_for_status()
            search_data = response.json()
            
            # 检查搜索结果
            if "error" in search_data:
                error_msg = f"SearxNG搜索失败: {search_data['error']}"
                await emitter.update_status(error_msg, True, "web_search")
                return json.dumps({"error": search_data["error"], "success": False}, ensure_ascii=False, indent=2)
            
            results = search_data.get("results", [])
            if not results:
                await emitter.update_status("未找到搜索结果", True, "web_search")
                return json.dumps({
                    "error": "未找到匹配的搜索结果",
                    "success": False,
                    "query": query,
                    "total_count": 0
                }, ensure_ascii=False, indent=2)
            
            # 处理搜索结果
            processed_results = []
            for i, result in enumerate(results[:limit]):
                result_info = {
                    "title": result.get("title", "").strip(),
                    "url": result.get("url", "").strip(),
                    "content": result.get("content", "").strip(),
                    "engine": result.get("engine", ""),
                    "parsed_url": result.get("parsed_url", []),
                    "template": result.get("template", ""),
                    "positions": result.get("positions", []),
                    "score": result.get("score", 0),
                    "website_type": self._identify_website_type(result.get("url", "")),
                    "index": i + 1
                }
                
                if result_info["title"] and result_info["url"]:
                    processed_results.append(result_info)
            
            if not processed_results:
                await emitter.update_status("未找到有效的搜索结果", True, "web_search")
                return json.dumps({
                    "error": "未找到有效的搜索结果",
                    "success": False,
                    "query": query,
                    "total_count": 0
                }, ensure_ascii=False, indent=2)
            
            # 提取网页内容
            if self.valves.ENABLE_CONTENT_EXTRACTION:
                await emitter.update_status(
                    f"正在提取 {len(processed_results)} 个网页的内容...",
                    False,
                    "content_extraction"
                )
                
                # 收集所有URL进行批量内容提取
                urls = [result["url"] for result in processed_results]
                extracted_contents = await self._extract_contents_batch(urls)
                
                # 将提取的内容合并到搜索结果中
                url_to_content = {content["url"]: content for content in extracted_contents}
                
                for result in processed_results:
                    url = result["url"]
                    if url in url_to_content:
                        content_data = url_to_content[url]
                        result["extracted_content"] = {
                            "success": content_data["success"],
                            "title": content_data["title"],
                            "content": content_data["content"],
                            "extracted_at": content_data["extracted_at"],
                            "error": content_data["error"]
                        }
                    else:
                        result["extracted_content"] = {
                            "success": False,
                            "title": "",
                            "content": "",
                            "extracted_at": 0,
                            "error": "未找到提取结果"
                        }
                
                # 统计成功提取的内容
                successful_extractions = sum(1 for content in extracted_contents if content["success"])
                await emitter.update_status(
                    f"内容提取完成! 成功提取 {successful_extractions}/{len(extracted_contents)} 个网页内容",
                    False,
                    "content_extraction"
                )
            
            # 发送引用信息
            for result_info in processed_results:
                citation_content = f"**{result_info['title']}**\n\n"
                citation_content += f"**URL:** {result_info['url']}\n\n"
                citation_content += f"**网站类型:** {result_info['website_type']}\n\n"
                
                # 添加搜索摘要
                if result_info['content']:
                    citation_content += f"**搜索摘要:** {result_info['content']}\n\n"
                
                # 添加提取的完整内容
                if self.valves.ENABLE_CONTENT_EXTRACTION and result_info.get('extracted_content'):
                    extracted = result_info['extracted_content']
                    if extracted['success'] and extracted['content']:
                        # 限制内容长度以避免过长
                        content = extracted['content']
                        if len(content) > 2000:
                            content = content[:2000] + "..."
                        citation_content += f"**完整内容:** {content}\n\n"
                        
                        if extracted['title'] and extracted['title'] != result_info['title']:
                            citation_content += f"**提取标题:** {extracted['title']}\n\n"
                    elif not extracted['success']:
                        citation_content += f"**内容提取失败:** {extracted.get('error', '未知错误')}\n\n"
                
                if result_info['engine']:
                    citation_content += f"**搜索引擎:** {result_info['engine']}\n\n"
                if result_info['score']:
                    citation_content += f"**相关性评分:** {result_info['score']}\n\n"
                
                await emitter.send_citation(
                    result_info['title'], 
                    result_info['url'], 
                    citation_content
                )
            
            success_msg = f"搜索完成! 找到 {len(processed_results)} 个相关结果"
            if self.valves.ENABLE_CONTENT_EXTRACTION:
                successful_extractions = sum(1 for r in processed_results 
                                           if r.get('extracted_content', {}).get('success', False))
                success_msg += f"，成功提取 {successful_extractions} 个网页内容"
            
            await emitter.update_status(success_msg, True, "web_search")
            
            prompt = f"""
关键要求：
1. 紧扣用户问题，不要偏离主题
2. 从信息源中筛选出与问题直接相关的内容
3. 忽略信息源中与问题无关的内容（如广告、导航、无关段落等）
4. 只使用能够回答用户问题的信息源，不要强行使用所有源
5. 如果某个信息源与问题无关，可以忽略它
6. 在回答中使用引用，如[1],[2],[3]等
7. 在文末使用markdown链接格式标注相关来源：[标题](链接)"""
            
            # 返回格式化的结果
            formatted_result = {
                "success": True,
                "query": query,
                "limit": limit,
                "language": language,
                "categories": categories,
                "time_range": time_range,
                "safesearch": safesearch,
                "total_count": len(processed_results),
                "returned_count": len(processed_results),
                "source": "searxng",
                "content_extraction_enabled": self.valves.ENABLE_CONTENT_EXTRACTION,
                "prompt": prompt,
                "results": processed_results,
                "search_info": {
                    "query": search_data.get("query", query),
                    "number_of_results": search_data.get("number_of_results", 0),
                    "engines": search_data.get("engines", []),
                    "answers": search_data.get("answers", []),
                    "corrections": search_data.get("corrections", []),
                    "infoboxes": search_data.get("infoboxes", []),
                    "suggestions": search_data.get("suggestions", [])
                }
            }
            
            # 添加内容提取统计信息
            if self.valves.ENABLE_CONTENT_EXTRACTION:
                successful_extractions = sum(1 for r in processed_results 
                                           if r.get('extracted_content', {}).get('success', False))
                formatted_result["content_extraction_stats"] = {
                    "total_attempted": len(processed_results),
                    "successful": successful_extractions,
                    "failed": len(processed_results) - successful_extractions,
                    "success_rate": round(successful_extractions / len(processed_results) * 100, 2) if processed_results else 0
                }
            
            return json.dumps(formatted_result, ensure_ascii=False, indent=2)
            
        except requests.exceptions.Timeout:
            error_msg = f"搜索请求超时 (超过 {self.valves.SEARXNG_TIMEOUT} 秒)"
            await emitter.update_status(error_msg, True, "web_search")
            return json.dumps({"error": error_msg, "success": False}, ensure_ascii=False, indent=2)
        except requests.exceptions.RequestException as e:
            error_msg = f"搜索请求失败: {str(e)}"
            await emitter.update_status(error_msg, True, "web_search")
            return json.dumps({"error": error_msg, "success": False}, ensure_ascii=False, indent=2)
        except Exception as e:
            error_msg = f"搜索过程中发生错误: {str(e)}"
            await emitter.update_status(error_msg, True, "web_search")
            return json.dumps({"error": str(e), "success": False}, ensure_ascii=False, indent=2)
