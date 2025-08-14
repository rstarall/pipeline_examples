"""
title: Semantic Scholar Academic Paper Search Tool
author: Assistant
version: 1.0
license: MIT
description: A tool for searching academic papers using Semantic Scholar MCP service
"""

import asyncio
import aiohttp
import json
import time
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
        self.session_id = None
        self._session_initialized = False
        
    class Valves(BaseModel):
        MCP_SERVER_URL: str = Field(
            default="http://localhost:8992",
            description="Semantic Scholar MCP服务器地址/MCP server URL for Semantic Scholar service",
        )
        MCP_TIMEOUT: int = Field(
            default=30,
            description="MCP服务连接超时时间（秒）/MCP service connection timeout in seconds",
        )
        DEFAULT_LIMIT: int = Field(
            default=10,
            description="默认搜索论文数量/Default number of papers to search",
        )
        MAX_LIMIT: int = Field(
            default=50,
            description="最大搜索论文数量限制/Maximum limit for paper search",
        )

    async def _initialize_mcp_session(self) -> bool:
        if self._session_initialized:
            return True
            
        if not self.valves.MCP_SERVER_URL:
            raise Exception("MCP服务器地址未配置")
        
        try:
            mcp_url = f"{self.valves.MCP_SERVER_URL.strip().rstrip('/')}/mcp"
            
            # Step 1: 发送initialize请求
            initialize_request = {
                "jsonrpc": "2.0",
                "method": "initialize", 
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "sampling": {},
                        "roots": {"listChanged": True}
                    },
                    "clientInfo": {
                        "name": "Semantic Scholar Tool",
                        "version": "1.0.0"
                    }
                },
                "id": "init-1"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    mcp_url,
                    json=initialize_request,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream"
                    },
                    timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                ) as response:
                    if response.status == 200:
                        # 检查响应头中的session ID
                        server_session_id = response.headers.get("Mcp-Session-Id")
                        if server_session_id:
                            self.session_id = server_session_id
                        
                        # 处理响应
                        content_type = response.headers.get("Content-Type", "")
                        
                        if "text/event-stream" in content_type:
                            # 处理SSE流
                            init_response = None
                            async for line in response.content:
                                line_str = line.decode('utf-8').strip()
                                if line_str.startswith('data: '):
                                    try:
                                        data = json.loads(line_str[6:])
                                        if data.get("id") == "init-1":
                                            init_response = data
                                            break
                                    except json.JSONDecodeError:
                                        continue
                        else:
                            init_response = await response.json()
                        
                        if not init_response:
                            raise Exception("No initialize response received")
                        
                        if "error" in init_response:
                            raise Exception(f"MCP initialize error: {init_response['error']}")
                        
                        # Step 2: 发送initialized通知
                        initialized_notification = {
                            "jsonrpc": "2.0",
                            "method": "notifications/initialized"
                        }
                        
                        headers = {
                            "Content-Type": "application/json",
                            "Accept": "application/json, text/event-stream"
                        }
                        if self.session_id:
                            headers["Mcp-Session-Id"] = self.session_id
                        
                        async with session.post(
                            mcp_url,
                            json=initialized_notification,
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                        ) as notify_response:
                            if notify_response.status not in [200, 202]:
                                pass  # 忽略initialized通知失败
                        
                        self._session_initialized = True
                        return True
                    else:
                        error_text = await response.text()
                        raise Exception(f"Initialize failed - HTTP {response.status}: {error_text}")
                        
        except Exception as e:
            raise Exception(f"MCP会话初始化失败: {e}")

    async def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self.valves.MCP_SERVER_URL:
            return {"error": "MCP服务器地址未配置"}
        
        # 确保会话已初始化
        if not self._session_initialized:
            await self._initialize_mcp_session()
        
        try:
            mcp_url = f"{self.valves.MCP_SERVER_URL.strip().rstrip('/')}/mcp"
            
            # MCP JSON-RPC格式请求体
            jsonrpc_payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                },
                "id": f"mcp_{tool_name}_{int(time.time())}"
            }
            
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream"
            }
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    mcp_url,
                    headers=headers,
                    json=jsonrpc_payload,
                    timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                ) as response:
                    if response.status == 200:
                        content_type = response.headers.get("Content-Type", "")
                        if "text/event-stream" in content_type:
                            # 处理SSE流
                            result = None
                            request_id = jsonrpc_payload["id"]
                            async for line in response.content:
                                line_str = line.decode('utf-8').strip()
                                if line_str.startswith('data: '):
                                    try:
                                        data = json.loads(line_str[6:])
                                        if data.get("id") == request_id:
                                            result = data
                                            break
                                    except json.JSONDecodeError:
                                        continue
                        else:
                            result = await response.json()
                        
                        if not result:
                            return {"error": "No response received"}
                        
                        # 处理MCP JSON-RPC响应
                        if "result" in result:
                            payload = result["result"]
                            
                            # FastMCP将工具返回值包装在content中
                            if isinstance(payload, dict) and "content" in payload and payload["content"]:
                                # 提取文本内容
                                text_content = ""
                                for content in payload["content"]:
                                    if content.get("type") == "text":
                                        text_content += content.get("text", "") + "\n"
                                
                                if text_content:
                                    try:
                                        # 解析JSON字符串为字典
                                        return json.loads(text_content.strip())
                                    except json.JSONDecodeError:
                                        # 如果不是JSON，返回原始文本
                                        return {"raw_text": text_content.strip()}
                                
                                # content存在但为空
                                return {"error": "Empty content received"}
                            
                            # 直接返回payload（兼容性处理）
                            return payload
                            
                        elif "error" in result:
                            return {"error": f"MCP错误: {result['error'].get('message', 'Unknown error')}"}
                        else:
                            return {"error": "无效的MCP响应格式"}
                    else:
                        return {"error": f"HTTP {response.status}: {await response.text()}"}
                        
        except asyncio.TimeoutError:
            return {"error": "请求超时"}
        except aiohttp.ClientError as e:
            return {"error": f"HTTP请求失败: {str(e)}"}
        except Exception as e:
            return {"error": f"MCP工具调用失败: {str(e)}"}

    async def search_academic_papers(
        self,
        query: str = Field(..., description="The search query for academic papers using English，most using academic english "),
        limit: Optional[int] = None,
        offset: int = 0,
        __event_emitter__: EmitterType = None
    ) -> str:
        """
        Search academic papers using Semantic Scholar database. This tool searches for scholarly articles, 
        research papers, and academic publications based on the provided query terms.
        
        Use this tool when users ask about:
        - Scientific research papers
        - Academic literature search
        - Scholar articles on specific topics
        - Research publications by authors
        - Citations and academic references
        - Peer-reviewed papers
        - Conference papers and journal articles
        
        The tool supports complex academic queries including author names, technical terms, 
        research topics, and specific methodologies.

        :param query: The search query for academic papers using English,most using academic english
        :param limit: Maximum number of papers to return (default: configured default, max: configured max)  
        :param offset: Number of papers to skip for pagination (default: 0)
        :param __event_emitter__: Optional event emitter for status updates
        :return: JSON formatted search results containing paper details
        """
        emitter = EventEmitter(__event_emitter__)
        
        # 验证参数
        if not query or not query.strip():
            await emitter.update_status("搜索查询不能为空", True, "search_papers")
            return json.dumps({"error": "搜索查询不能为空", "success": False}, ensure_ascii=False, indent=2)
        
        # 设置默认值和限制
        if limit is None:
            limit = self.valves.DEFAULT_LIMIT
        limit = min(limit, self.valves.MAX_LIMIT)
        offset = max(0, offset)
        
        await emitter.update_status(
            f"正在搜索学术论文: {query} (限制: {limit}篇, 偏移: {offset})",
            False,
            "search_papers"
        )
        
        try:
            # 调用MCP工具执行搜索
            tool_args = {
                "query": query.strip(),
                "limit": limit,
                "offset": offset
            }
            
            result = await self._call_mcp_tool("search_papers", tool_args)
            
            # 检查MCP调用是否成功
            if "error" in result and result["error"]:
                error_msg = f"MCP调用失败: {result['error']}"
                await emitter.update_status(error_msg, True, "search_papers")
                return json.dumps({"error": result["error"], "success": False}, ensure_ascii=False, indent=2)
            
            # 检查搜索是否成功
            if not result.get("success", False):
                # 获取具体的错误信息
                server_error = result.get("error")
                if server_error:
                    error_msg = f"学术论文搜索失败: {server_error}"
                else:
                    error_msg = f"学术论文搜索失败: 未找到匹配的论文 (查询: {query}, 限制: {limit}篇)"
                
                await emitter.update_status(error_msg, True, "search_papers")
                
                # 添加调试信息
                debug_info = {
                    "error": error_msg,
                    "success": False,
                    "debug_info": {
                        "query": query,
                        "limit": limit,
                        "offset": offset,
                        "mcp_response": result
                    }
                }
                return json.dumps(debug_info, ensure_ascii=False, indent=2)
            
            # 处理搜索结果
            papers = result.get("results", [])
            total_count = result.get("total_count", len(papers))
            
            # 为每篇找到的论文发送详细的引用信息
            for i, paper in enumerate(papers, 1):
                title = paper.get("title", f"Paper {i}")
                paper_url = paper.get("url", "")
                
                # 构建详细的论文信息
                citation_content = f"**{title}**\n\n"
                
                # 作者信息
                authors = paper.get("authors", [])
                if authors:
                    author_names = []
                    for author in authors[:5]:  # 显示前5个作者
                        author_name = author.get("name", "Unknown Author")
                        author_id = author.get("authorId")
                        if author_id:
                            author_names.append(f"{author_name} (ID: {author_id})")
                        else:
                            author_names.append(author_name)
                    
                    if len(authors) > 5:
                        author_names.append(f"... 等 {len(authors)} 位作者")
                    
                    citation_content += f"**Authors:** {', '.join(author_names)}\n\n"
                
                # 基本信息
                if paper.get("year"):
                    citation_content += f"**Year:** {paper.get('year')}\n\n"
                if paper.get("venue"):
                    citation_content += f"**Venue:** {paper.get('venue')}\n\n"
                
                # 引用统计
                if paper.get("citationCount"):
                    citation_content += f"**Citations:** {paper.get('citationCount')}\n\n"
                if paper.get("referenceCount"):
                    citation_content += f"**References:** {paper.get('referenceCount')}\n\n"
                if paper.get("influentialCitationCount"):
                    citation_content += f"**Influential Citations:** {paper.get('influentialCitationCount')}\n\n"
                
                # 开放获取和PDF信息
                if paper.get("isOpenAccess"):
                    citation_content += f"**Open Access:** Yes\n\n"
                    
                # PDF下载链接
                open_access_pdf = paper.get("openAccessPdf")
                if open_access_pdf and open_access_pdf.get("url"):
                    pdf_url = open_access_pdf.get("url")
                    pdf_status = open_access_pdf.get("status", "unknown")
                    pdf_license = open_access_pdf.get("license", "unknown")
                    citation_content += f"**PDF Download:** [Download PDF]({pdf_url})\n\n"
                    citation_content += f"**PDF Status:** {pdf_status}\n\n"
                    if pdf_license != "unknown":
                        citation_content += f"**License:** {pdf_license}\n\n"
                
                # DOI和外部标识
                external_ids = paper.get("externalIds")
                if external_ids:
                    if external_ids.get("DOI"):
                        doi = external_ids.get("DOI")
                        citation_content += f"**DOI:** [{doi}](https://doi.org/{doi})\n\n"
                    if external_ids.get("CorpusId"):
                        citation_content += f"**Corpus ID:** {external_ids.get('CorpusId')}\n\n"
                
                # 研究领域
                fields_of_study = paper.get("fieldsOfStudy", [])
                if fields_of_study:
                    citation_content += f"**Fields of Study:** {', '.join(fields_of_study)}\n\n"
                
                # 期刊信息
                journal = paper.get("journal")
                if journal:
                    journal_name = journal.get("name")
                    if journal_name:
                        citation_content += f"**Journal:** {journal_name}\n\n"
                    if journal.get("volume"):
                        citation_content += f"**Volume:** {journal.get('volume')}\n\n"
                    if journal.get("pages"):
                        citation_content += f"**Pages:** {journal.get('pages')}\n\n"
                
                # TLDR摘要
                tldr = paper.get("tldr")
                if tldr and tldr.get("text"):
                    citation_content += f"**TL;DR:** {tldr.get('text')}\n\n"
                
                # 摘要
                abstract = paper.get("abstract")
                if abstract and abstract != "No abstract available":
                    # 限制摘要长度
                    if len(abstract) > 800:
                        abstract = abstract[:800] + "..."
                    citation_content += f"**Abstract:** {abstract}\n\n"
                
                # Paper ID
                if paper.get("paperId"):
                    citation_content += f"**Paper ID:** {paper.get('paperId')}\n\n"
                
                # Semantic Scholar URL
                if paper_url:
                    citation_content += f"**Semantic Scholar:** [View Paper]({paper_url})\n\n"
                
                await emitter.send_citation(title, paper_url or "https://www.semanticscholar.org/", citation_content)
            
            success_msg = f"搜索完成! 找到 {len(papers)} 篇论文 (总共 {total_count} 篇相关论文)"
            await emitter.update_status(success_msg, True, "search_papers")
            
            prompt = """## 📝 学术分析要求

### 🔍 深度分析
1. **摘要精读**: 仔细分析每篇论文的研究问题、方法、发现和结论
2. **方法评述**: 评估研究方法的优势与局限性
3. **关键发现**: 提取重要数据、结果、创新突破点
4. **学术价值**: 基于引用数、研究质量评估论文贡献
5. **跨论文比较**: 对比不同研究的方法和结果，识别趋势和争议

### 📚 引用格式要求（必须严格遵循）
**正文引用**: 使用 [论文标题](Semantic Scholar链接)
**回答末尾**: 必须显示完整论文引用列表

**固定输出格式示例**:

## 分析内容
论文 1: 论文标题
    标题: 论文标题
    作者: 作者姓名 et al.
    发表年份: 年份
    期刊/会议: 期刊或会议名称
    被引用次数: 引用次数
    摘要精读分析: 对论文摘要的深入分析，包括研究问题、方法、发现和结论的详细解读。
    研究方法评述:
    优势: 研究方法的优势和创新点描述。
    局限性: 研究方法的局限性和不足分析。
    关键发现提取: 论文中的重要发现、数据结果和创新突破点。
    学术价值评估: 基于引用数、研究质量等因素的学术贡献评估。
    Semantic Scholar 链接: https://www.semanticscholar.org/paper/paper_id
    DOI: https://doi.org/doi_number
    下载链接: pdf下载链接 (如有)
## 综合分析
1. 对所有论文进行综合分析，包括研究问题、方法、发现和结论的详细解读。
## 论文引用
1. **论文标题**
   引用: 作者姓名 et al. (年份). 论文标题. 期刊/会议名称, 卷号(期号), 页码.

**重要**: 必须使用此格式，确保引用输出稳定一致。"""
            # 返回格式化的结果
            formatted_result = {
                "success": True,
                "query": query,
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "returned_count": len(papers),
                "source": result.get("source", "semantic_scholar"),
                "results": papers,
                "prompt": prompt,
            }
            
            return json.dumps(formatted_result, ensure_ascii=False, indent=2)
            
        except Exception as e:
            error_msg = f"搜索过程中发生错误: {str(e)}"
            await emitter.update_status(error_msg, True, "search_papers")
            return json.dumps({"error": str(e), "success": False}, ensure_ascii=False, indent=2)
