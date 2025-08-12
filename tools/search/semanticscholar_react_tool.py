"""
title: Semantic Scholar ReAct Academic Paper Search Tool
author: Assistant
version: 1.0
license: MIT
description: An advanced academic paper search tool using ReAct methodology with LLM optimization
"""

import asyncio
import aiohttp
import json
import time
import requests
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
        self.react_state = {}
        self.token_stats = {
            "input_tokens": 0,
            "output_tokens": 0, 
            "total_tokens": 0,
            "api_calls": 0
        }
        
    class Valves(BaseModel):
        model_config = {"arbitrary_types_allowed": True}
        
        # MCP配置
        MCP_SERVER_URL: str = Field(
            default="http://localhost:8992",
            description="Semantic Scholar MCP服务器地址/MCP server URL for Semantic Scholar service",
        )
        MCP_TIMEOUT: int = Field(
            default=30,
            description="MCP服务连接超时时间（秒）/MCP service connection timeout in seconds",
        )
        
        # OpenAI配置
        OPENAI_API_KEY: str = Field(
            default="",
            description="OpenAI API密钥/OpenAI API key for LLM optimization",
        )
        OPENAI_BASE_URL: str = Field(
            default="https://api.openai.com/v1",
            description="OpenAI API基础URL/OpenAI API base URL",
        )
        OPENAI_MODEL: str = Field(
            default="gpt-4o-mini",
            description="OpenAI模型名称/OpenAI model name",
        )
        OPENAI_TIMEOUT: int = Field(
            default=60,
            description="OpenAI API超时时间（秒）/OpenAI API timeout in seconds",
        )
        OPENAI_MAX_TOKENS: int = Field(
            default=4000,
            description="OpenAI最大输出token数/Max output tokens for OpenAI",
        )
        OPENAI_TEMPERATURE: float = Field(
            default=0.7,
            description="OpenAI温度参数/OpenAI temperature parameter",
        )
        
        # ReAct配置
        MAX_REACT_ITERATIONS: int = Field(
            default=4,
            description="最大ReAct迭代次数/Maximum ReAct iterations",
        )
        MIN_PAPERS_THRESHOLD: int = Field(
            default=8,
            description="最小论文收集阈值/Minimum papers collection threshold",
        )
        DEFAULT_LIMIT: int = Field(
            default=12,
            description="默认搜索论文数量/Default number of papers to search",
        )

    def _call_openai_api(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        if not self.valves.OPENAI_API_KEY:
            return "错误: 未设置OpenAI API密钥"
        
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        # 统计输入token数量（用字符数估计）
        input_text = "".join(msg.get("content", "") for msg in messages)
        input_tokens = len(input_text)
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": messages,
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.OPENAI_TEMPERATURE,
        }
        
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.valves.OPENAI_TIMEOUT)
            response.raise_for_status()
            result = response.json()
            
            response_content = result["choices"][0]["message"]["content"]
            output_tokens = len(response_content)
            
            # 更新统计信息
            self.token_stats["input_tokens"] += input_tokens
            self.token_stats["output_tokens"] += output_tokens
            self.token_stats["total_tokens"] += input_tokens + output_tokens
            self.token_stats["api_calls"] += 1
            
            return response_content
        except Exception as e:
            return f"OpenAI API调用错误: {str(e)}"

    async def _initialize_mcp_session(self) -> bool:
        if self._session_initialized:
            return True
            
        if not self.valves.MCP_SERVER_URL:
            raise Exception("MCP服务器地址未配置")
        
        try:
            mcp_url = f"{self.valves.MCP_SERVER_URL.strip().rstrip('/')}/mcp"
            
            initialize_request = {
                "jsonrpc": "2.0",
                "method": "initialize", 
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"sampling": {}, "roots": {"listChanged": True}},
                    "clientInfo": {"name": "Semantic Scholar ReAct Tool", "version": "1.0.0"}
                },
                "id": "init-1"
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    mcp_url,
                    json=initialize_request,
                    headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
                    timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                ) as response:
                    if response.status == 200:
                        server_session_id = response.headers.get("Mcp-Session-Id")
                        if server_session_id:
                            self.session_id = server_session_id
                        
                        content_type = response.headers.get("Content-Type", "")
                        if "text/event-stream" in content_type:
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
                        
                        if "error" in init_response:
                            raise Exception(f"MCP initialize error: {init_response['error']}")
                        
                        # 发送initialized通知
                        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
                        if self.session_id:
                            headers["Mcp-Session-Id"] = self.session_id
                        
                        await session.post(
                            mcp_url,
                            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                            headers=headers,
                            timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                        )
                        
                        self._session_initialized = True
                        return True
                    else:
                        error_text = await response.text()
                        raise Exception(f"Initialize failed - HTTP {response.status}: {error_text}")
        except Exception as e:
            raise Exception(f"MCP会话初始化失败: {e}")

    async def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self._session_initialized:
            await self._initialize_mcp_session()
        
        try:
            mcp_url = f"{self.valves.MCP_SERVER_URL.strip().rstrip('/')}/mcp"
            
            jsonrpc_payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
                "id": f"mcp_{tool_name}_{int(time.time())}"
            }
            
            headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
            if self.session_id:
                headers["Mcp-Session-Id"] = self.session_id
            
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    mcp_url, headers=headers, json=jsonrpc_payload,
                    timeout=aiohttp.ClientTimeout(total=self.valves.MCP_TIMEOUT)
                ) as response:
                    if response.status == 200:
                        content_type = response.headers.get("Content-Type", "")
                        if "text/event-stream" in content_type:
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
                        
                        if "result" in result:
                            return result["result"]
                        elif "error" in result:
                            return {"error": f"MCP错误: {result['error'].get('message', 'Unknown error')}"}
                        else:
                            return {"error": "无效的MCP响应格式"}
                    else:
                        return {"error": f"HTTP {response.status}: {await response.text()}"}
        except Exception as e:
            return {"error": f"MCP工具调用失败: {str(e)}"}

    async def _reasoning_phase(self, user_message: str, emitter) -> Dict[str, Any]:
        await emitter.update_status("🤔 分析问题，制定搜索策略...", False, "reasoning")
        
        used_queries = list(self.react_state.get('query_terms_used', set()))
        
        reasoning_prompt = f"""你是专业的学术论文搜索助手。请基于用户问题制定搜索策略。

用户问题: {user_message}
已使用查询词: {used_queries}

**重要说明：**
- 使用Semantic Scholar搜索引擎，支持复杂学术查询
- 支持作者查询（如 "author:Smith machine learning"）
- 支持期刊查询（如 "venue:Nature artificial intelligence"）
- 支持技术术语组合（如 "transformer attention mechanism"）

**分析任务：**
1. 判断是否需要搜索论文？
2. 提取核心学术查询关键词
3. 避免重复已使用的查询词

**查询示例：**
- "机器学习医学影像" → "machine learning medical imaging"
- "Transformer架构研究" → "transformer architecture attention mechanism"
- "BERT自然语言处理" → "BERT natural language processing"

回复格式：
```json
{{
    "need_search": true/false,
    "query": "学术查询词",
    "reasoning": "分析过程",
    "sufficient_info": true/false
}}
```"""

        decision = self._call_openai_api("", reasoning_prompt, json_mode=True)
        
        try:
            decision_data = json.loads(decision)
            await emitter.update_status(f"推理完成: {decision_data.get('reasoning', '制定搜索策略')}", False, "reasoning")
            return decision_data
        except json.JSONDecodeError:
            return {"need_search": False, "sufficient_info": True, "reasoning": "解析失败"}

    async def _action_phase(self, query: str, limit: int = 10, offset: int = 0, emitter = None) -> Dict[str, Any]:
        await emitter.update_status(f"🔍 搜索论文: {query} (限制{limit}篇, 偏移{offset})", False, "search_papers")
        
        # 更新状态
        self.react_state["current_offset"] = offset
        self.react_state["current_limit"] = limit
        self.react_state.setdefault("query_offsets", {})[query] = offset
        
        # 调用MCP工具
        tool_args = {"query": query, "limit": limit, "offset": offset}
        result = await self._call_mcp_tool("search_papers", tool_args)
        
        # 记录查询历史
        self.react_state.setdefault('query_history', []).append(query)
        self.react_state.setdefault('query_terms_used', set()).add(query.lower())
        
        if "error" not in result:
            papers_count = len(result.get("results", []))
            await emitter.update_status(f"搜索完成，获得 {papers_count} 篇论文", False, "search_papers")
        else:
            await emitter.update_status(f"搜索失败: {result['error']}", False, "search_papers")
        
        return result

    async def _observation_phase(self, action_result: Dict[str, Any], query: str, user_message: str, emitter) -> Dict[str, Any]:
        await emitter.update_status("👁️ 分析搜索结果，提取关键信息...", False, "analysis")
        
        used_queries = list(self.react_state.get('query_terms_used', set()))
        current_iteration = self.react_state.get('current_iteration', 0)
        current_papers_count = len(self.react_state.get('papers_collected', []))
        min_papers_threshold = self.valves.MIN_PAPERS_THRESHOLD
        
        observation_prompt = f"""分析Semantic Scholar搜索结果，决定下一步行动：

用户问题: {user_message}
查询词: {query}
当前迭代: {current_iteration}/{self.valves.MAX_REACT_ITERATIONS}
已用查询: {used_queries}
当前论文数: {current_papers_count} 篇
最低要求: {min_papers_threshold} 篇

搜索结果:
{json.dumps(action_result, ensure_ascii=False, indent=2)}

**任务：**
1. 分析搜索结果中论文的相关性和质量
2. 提取关键论文信息
3. **重要**：判断论文数量是否足够 - 如果当前论文数({current_papers_count})少于最低要求({min_papers_threshold})，必须设置 need_more_search=true
4. 如需搜索，提供新的查询词和搜索策略

**决策规则：**
- 论文数量不足({current_papers_count} < {min_papers_threshold})：必须 need_more_search=true
- 论文质量不高或相关性不强：need_more_search=true
- 已达到最大迭代数且有基础论文：可以 need_more_search=false
- 论文数量充足且质量高：need_more_search=false

**输出格式：**
```json
{{
    "relevance_score": 0-10,
    "sufficient_info": true/false,
    "need_more_search": true/false,
    "suggested_query": "新查询词(if needed)",
    "extracted_keywords": ["关键词列表"],
    "key_papers": [
        {{
            "title": "论文标题",
            "authors": "作者",
            "year": "年份", 
            "venue": "期刊/会议",
            "abstract": "摘要(必须完整，不要遗漏任何信息)",
            "citation_count": "引用数",
            "relevance_weight": 0.0-1.0,
            "download_url": "pdf下载链接(openAccessPdf字段里提取，如果有)",
            "urls": ["链接列表"]
        }}
    ],
    "observation": "分析总结"
}}
```"""

        observation = self._call_openai_api("", observation_prompt, json_mode=True)
        
        try:
            observation_data = json.loads(observation)
            
            # 处理关键论文并发送引用
            key_papers = observation_data.get('key_papers', [])
            added_count = 0
            
            for paper in key_papers:
                # 检查重复
                title = paper.get('title', '').strip().lower()
                existing_papers = self.react_state.setdefault('papers_collected', [])
                
                if title and not any(existing.get('title', '').strip().lower() == title for existing in existing_papers):
                    existing_papers.append(paper)
                    added_count += 1
                    
                    # 发送引用
                    authors = paper.get('authors', '')
                    year = paper.get('year', '')
                    venue = paper.get('venue', '')
                    abstract = paper.get('abstract', 'No abstract available')
                    citation_count = paper.get('citation_count', 0)

                    urls = paper.get('urls', [])
                    
                    citation_content = f"**{paper.get('title', 'Unknown Title')}**\n\n"
                    if authors:
                        citation_content += f"**Authors:** {authors}\n\n"
                    if year:
                        citation_content += f"**Year:** {year}\n\n"
                    if venue:
                        citation_content += f"**Venue:** {venue}\n\n"
                    if citation_count:
                        citation_content += f"**Citations:** {citation_count}\n\n"
                    if urls:
                        citation_content += f"**Links:** {urls}\n\n"
                        
                    citation_content += f"**Abstract:** {abstract}\n"
                    
                    paper_url = urls[0] if urls else ""
                    await emitter.send_citation(paper.get('title', 'Unknown Title'), paper_url, citation_content)
            
            # 更新提取的关键词
            keywords = observation_data.get('extracted_keywords', [])
            if keywords:
                self.react_state.setdefault('extracted_keywords_history', set()).update(keywords)
            
            await emitter.update_status(
                f"分析完成: 发现{len(key_papers)}篇关键论文，新增{added_count}篇", 
                False, "analysis"
            )
            
            return observation_data
        except json.JSONDecodeError:
            # JSON解析失败时，如果论文数不足，强制继续搜索
            current_papers_count = len(self.react_state.get('papers_collected', []))
            if current_papers_count < self.valves.MIN_PAPERS_THRESHOLD:
                return {"sufficient_info": False, "need_more_search": True, "suggested_query": query, "observation": f"解析失败，当前仅{current_papers_count}篇论文，继续搜索"}
            else:
                return {"sufficient_info": True, "need_more_search": False, "observation": "解析失败"}

    async def _generate_final_answer(self, user_message: str, emitter) -> str:
        await emitter.update_status("📝 整理收集的论文信息，生成工具输出...", False, "generate_answer")
        
        papers = self.react_state.get('papers_collected', [])
        total_papers = len(papers)
        
        # 构建详细的论文信息，包含可用链接
        papers_detail = ""
        for i, paper in enumerate(papers[:20], 1):  # 限制在前20篇
            papers_detail += f"=== 📄 论文 {i} ===\n"
            papers_detail += f"标题: {paper.get('title', '未知')}\n"
            papers_detail += f"作者: {paper.get('authors', '未知')}\n"
            
            # 基本信息
            if paper.get('year'):
                papers_detail += f"发表年份: {paper.get('year')}\n"
            if paper.get('venue'):
                papers_detail += f"发表期刊/会议: {paper.get('venue')}\n"
            if paper.get('citation_count'):
                papers_detail += f"被引用次数: {paper.get('citation_count')}\n"
            if paper.get('influential_citation_count'):
                papers_detail += f"有影响力的引用: {paper.get('influential_citation_count')}\n"
            if paper.get('paper_id'):
                papers_detail += f"论文ID: {paper.get('paper_id')}\n"
            
            # 链接信息
            papers_detail += "📋 可用链接:\n"
            if paper.get('urls'):
                urls = paper.get('urls')
                if isinstance(urls, list) and urls:
                    for url in urls:
                        papers_detail += f"  • url: {url}\n"
                elif isinstance(urls, str):
                    papers_detail += f"  • url: {urls}\n"
            
            if paper.get('open_access_pdf'):
                papers_detail += f"  • 开放获取PDF: {paper.get('open_access_pdf')}\n"
            
            if paper.get('external_ids'):
                ext_ids = paper.get('external_ids')
                if isinstance(ext_ids, dict):
                    if ext_ids.get('DOI'):
                        papers_detail += f"  • DOI: https://doi.org/{ext_ids['DOI']}\n"
                    if ext_ids.get('ArXiv'):
                        papers_detail += f"  • ArXiv: https://arxiv.org/abs/{ext_ids['ArXiv']}\n"
                    if ext_ids.get('PubMed'):
                        papers_detail += f"  • PubMed: https://pubmed.ncbi.nlm.nih.gov/{ext_ids['PubMed']}\n"
            
            # 摘要
            if paper.get('abstract'):
                abstract = paper.get('abstract')
                # 保留完整摘要，但截断过长的内容
                if len(abstract) > 800:
                    abstract = abstract[:800] + "..."
                papers_detail += f"📝 摘要: {abstract}\n"
            
            # TLDR（如果有）
            if paper.get('tldr'):
                papers_detail += f"💡 核心观点: {paper.get('tldr')}\n"
            
            # 研究领域
            if paper.get('fields_of_study'):
                fields = paper.get('fields_of_study')
                if isinstance(fields, list):
                    papers_detail += f"🏷️ 研究领域: {', '.join(fields)}\n"
                elif isinstance(fields, str):
                    papers_detail += f"🏷️ 研究领域: {fields}\n"
            
            papers_detail += "\n" + "="*50 + "\n\n"
        
        # 构建简化的工具输出
        tool_output = f"""# 🔬 Semantic Scholar 搜索结果

## 查询信息
**问题**: {user_message}  
**论文数**: {total_papers} 篇 | **搜索轮次**: {len(self.react_state.get('search_history', []))} 轮

## 📝 学术分析要求

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
    跨论文比较: 与其他相关研究的对比分析。
    Semantic Scholar 链接: https://www.semanticscholar.org/paper/paper_id
    DOI: https://doi.org/doi_number
    下载链接: pdf下载链接 (如有)

## 论文引用
1. **论文标题**
   引用: 作者姓名 et al. (年份). 论文标题. 期刊/会议名称, 卷号(期号), 页码.  - [PDF下载](pdf_url) (如有)

**重要**: 必须使用此格式，确保引用输出稳定一致。

---

{papers_detail}

## 统计信息
论文: {total_papers}篇 | API调用: {self.token_stats['api_calls']}次 | Token: {self.token_stats['total_tokens']:,}字符"""
        
        await emitter.update_status("工具输出生成完成", True, "generate_answer")
        return tool_output
    
    def _get_current_time(self) -> str:
        """获取当前时间字符串"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    async def search_papers_with_react(
        self,
        user_question: str = Field(..., description="user question (only input English)"),
        __event_emitter__: EmitterType = None
    ) -> str:
        """
        Search and analyze academic papers using ReAct methodology to provide comprehensive research answers.
        """
        emitter = EventEmitter(__event_emitter__)
        
        if not user_question or not user_question.strip():
            await emitter.update_status("❌ 请提供有效的研究问题", True, "error")
            return "错误: 请提供有效的研究问题"
        
        # 初始化状态
        self.react_state = {
            "papers_collected": [],
            "query_history": [],
            "query_terms_used": set(),
            "extracted_keywords_history": set(),
            "current_iteration": 0,
            "current_offset": 0,
            "current_limit": self.valves.DEFAULT_LIMIT
        }
        
        self.token_stats = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "api_calls": 0}
        
        try:
            await emitter.update_status("🚀 启动ReAct学术搜索系统", False, "initialize")
            
            # 确保MCP会话初始化
            await self._initialize_mcp_session()
            await emitter.update_status("✅ MCP连接建立", False, "initialize")
            
            # ReAct主循环
            max_iterations = self.valves.MAX_REACT_ITERATIONS
            
            # 1. 初始推理
            decision = await self._reasoning_phase(user_question, emitter)
            
            # 检查是否达到论文阈值，未达到则强制进入搜索循环
            collected_count = len(self.react_state.get('papers_collected', []))
            if (not decision.get("need_search", False) or decision.get("sufficient_info", False)) and collected_count >= self.valves.MIN_PAPERS_THRESHOLD:
                return await self._generate_final_answer(user_question, emitter)
            # 否则强制进入至少一轮搜索
            
            # 2. Action-Observation循环
            current_query = decision.get("query", "")
            
            # 确保至少有一个初始查询
            if not current_query:
                current_query = "academic research"  # 默认查询作为兜底
            
            while self.react_state['current_iteration'] < max_iterations and current_query:
                self.react_state['current_iteration'] += 1
                
                await emitter.update_status(
                    f"🔄 第 {self.react_state['current_iteration']}/{max_iterations} 轮搜索", 
                    False, "iteration"
                )
                
                # Action阶段
                current_offset = self.react_state.get("current_offset", 0)
                current_limit = self.react_state.get("current_limit", self.valves.DEFAULT_LIMIT)
                
                action_result = await self._action_phase(current_query, current_limit, current_offset, emitter)
                
                if "error" in action_result:
                    await emitter.update_status(f"❌ 搜索失败: {action_result['error']}", False, "error")
                    break
                
                # Observation阶段
                observation = await self._observation_phase(action_result, current_query, user_question, emitter)
                
                # 检查是否达到论文阈值
                collected_count = len(self.react_state['papers_collected'])
                if collected_count >= self.valves.MIN_PAPERS_THRESHOLD:
                    await emitter.update_status(
                        f"✅ 已收集足够论文 ({collected_count}篇 >= {self.valves.MIN_PAPERS_THRESHOLD}篇)", 
                        False, "threshold_reached"
                    )
                    # 达到阈值后可以根据LLM判断是否停止
                    if not observation.get("need_more_search", False) or observation.get("sufficient_info", False):
                        break
                else:
                    # 未达到阈值时强制继续，不因LLM判断而停止
                    await emitter.update_status(
                        f"⚠️ 论文数不足 ({collected_count}篇 < {self.valves.MIN_PAPERS_THRESHOLD}篇)，强制继续搜索", 
                        False, "force_continue"
                    )
                
                # 获取下一个查询并处理分页逻辑
                next_query = observation.get("suggested_query", "")
                used_queries = self.react_state['query_terms_used']
                current_limit = self.react_state.get("current_limit", self.valves.DEFAULT_LIMIT)
                
                # 如果论文数不足且无新查询或查询重复，启用分页机制
                if collected_count < self.valves.MIN_PAPERS_THRESHOLD:
                    if not next_query or next_query.lower() in used_queries:
                        # 使用当前查询进行分页拉取
                        if current_query:  # 确保有查询可用
                            self.react_state["current_offset"] = self.react_state.get("current_offset", 0) + current_limit
                            # current_query 保持不变
                            await emitter.update_status(
                                f"🔄 无新查询，启用分页 (offset={self.react_state['current_offset']})", 
                                False, "pagination"
                            )
                        else:
                            # 连当前查询都没有，使用兜底查询
                            current_query = "research papers"
                            self.react_state["current_offset"] = 0
                            await emitter.update_status("🔧 使用兜底查询策略", False, "fallback_query")
                    else:
                        # 使用新查询并重置offset
                        current_query = next_query
                        self.react_state["current_offset"] = 0
                        await emitter.update_status(f"🆕 切换新查询: {next_query}", False, "new_query")
                else:
                    # 已达到阈值，可以按正常逻辑处理
                    if not next_query or next_query.lower() in used_queries:
                        await emitter.update_status("⚠️ 检测到重复查询，停止搜索", False, "duplicate_query")
                        break
                    current_query = next_query
                    self.react_state["current_offset"] = 0
            
            # 3. 生成最终答案
            final_answer = await self._generate_final_answer(user_question, emitter)
            
            return final_answer
            
        except Exception as e:
            error_msg = f"❌ ReAct搜索过程出错: {str(e)}"
            await emitter.update_status(error_msg, True, "error")
            return error_msg
