"""
title: SearxNG OpenAI Pipeline
author: open-webui
date: 2024-12-20
version: 2.0
license: MIT
description: 基于SearxNG API的联网搜索pipeline，简化版本
requirements: requests, pydantic, aiohttp, beautifulsoup4, asyncio

阶段说明：
1. 阶段1: 问题优化 - 根据用户历史问题和当前问题输出优化后的问题
2. 阶段2: 网络搜索 - 使用SearxNG进行搜索并筛选最相关的结果
3. 阶段3: 内容获取 - 并发获取选中网页的内容
4. 阶段4: 生成最终回答 - 基于获取的内容生成准确的回答
"""

import os
import json
import requests
import asyncio
import aiohttp
import time
import re
from typing import List, Union, Generator, Iterator, Dict, Any
from pydantic import BaseModel
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup

# 后端阶段标题映射
STAGE_TITLES = {
    "query_optimization": "问题优化",
    "web_search": "网络搜索",
    "content_fetch": "内容获取",
    "final_answer": "生成最终回答",
}

STAGE_GROUP = {
    "query_optimization": "stage_group_1",
    "web_search": "stage_group_2",
    "content_fetch": "stage_group_3",
    "final_answer": "stage_group_4",
}

class Pipeline:
    class Valves(BaseModel):
        # SearxNG API配置
        SEARXNG_URL: str
        SEARXNG_SEARCH_COUNT: int
        SEARXNG_LANGUAGE: str
        SEARXNG_TIMEOUT: int
        SEARXNG_CATEGORIES: str
        SEARXNG_TIME_RANGE: str
        SEARXNG_SAFESEARCH: int
        
        # OpenAI配置
        OPENAI_API_KEY: str
        OPENAI_BASE_URL: str
        OPENAI_MODEL: str
        OPENAI_TIMEOUT: int
        OPENAI_MAX_TOKENS: int
        OPENAI_TEMPERATURE: float
        
        # Pipeline配置
        ENABLE_STREAMING: bool
        DEBUG_MODE: bool
        SELECTED_URLS_COUNT: int
        CONTENT_FETCH_TIMEOUT: int
        MAX_CONTENT_LENGTH: int
        
        # 历史会话配置
        HISTORY_TURNS: int

    def __init__(self):
        self.name = "SearxNG Search OpenAI Pipeline"
        
        # 初始化token统计
        self.token_stats = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        }
        
        self.valves = self.Valves(
            **{
                # SearxNG搜索配置
                "SEARXNG_URL": os.getenv("SEARXNG_URL", "http://117.50.252.245:8081"),
                "SEARXNG_SEARCH_COUNT": int(os.getenv("SEARXNG_SEARCH_COUNT", "20")),
                "SEARXNG_LANGUAGE": os.getenv("SEARXNG_LANGUAGE", "zh-CN"),
                "SEARXNG_TIMEOUT": int(os.getenv("SEARXNG_TIMEOUT", "15")),
                "SEARXNG_CATEGORIES": os.getenv("SEARXNG_CATEGORIES", "general"),
                "SEARXNG_TIME_RANGE": os.getenv("SEARXNG_TIME_RANGE", ""),
                "SEARXNG_SAFESEARCH": int(os.getenv("SEARXNG_SAFESEARCH", "0")),
                
                # OpenAI配置
                "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
                "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
                "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "google/gemini-2.5-flash"),
                "OPENAI_TIMEOUT": int(os.getenv("OPENAI_TIMEOUT", "60")),
                "OPENAI_MAX_TOKENS": int(os.getenv("OPENAI_MAX_TOKENS", "4000")),
                "OPENAI_TEMPERATURE": float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
                
                # Pipeline配置
                "ENABLE_STREAMING": os.getenv("ENABLE_STREAMING", "true").lower() == "true",
                "DEBUG_MODE": os.getenv("DEBUG_MODE", "false").lower() == "true",
                "SELECTED_URLS_COUNT": int(os.getenv("SELECTED_URLS_COUNT", "10")),
                "CONTENT_FETCH_TIMEOUT": int(os.getenv("CONTENT_FETCH_TIMEOUT", "10")),
                "MAX_CONTENT_LENGTH": int(os.getenv("MAX_CONTENT_LENGTH", "5000")),
                
                # 历史会话配置
                "HISTORY_TURNS": int(os.getenv("HISTORY_TURNS", "3")),
            }
        )

    async def on_startup(self):
        print(f"SearxNG Search OpenAI Pipeline启动: {__name__}")
        
        # 验证必需的API密钥
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")
            
        # 测试SearxNG API连接
        try:
            print("🔧 开始测试SearxNG API连接...")
            test_response = self._search_searxng("test query")
            if test_response and "results" in test_response:
                print("✅ SearxNG搜索API连接成功")
            else:
                print("⚠️ SearxNG搜索API测试失败")
        except Exception as e:
            print(f"❌ SearxNG搜索API连接失败: {e}")

    async def on_shutdown(self):
        print(f"SearxNG Search OpenAI Pipeline关闭: {__name__}")

    def _estimate_tokens(self, text: str) -> int:
        """简单的token估算函数"""
        if not text:
            return 0
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        english_text = ''.join(char if not ('\u4e00' <= char <= '\u9fff') else ' ' for char in text)
        english_words = len([word for word in english_text.split() if word.strip()])
        estimated_tokens = chinese_chars + int(english_words * 1.3)
        return max(estimated_tokens, 1)

    def _add_input_tokens(self, text: str):
        """添加输入token统计"""
        tokens = self._estimate_tokens(text)
        self.token_stats["input_tokens"] += tokens
        self.token_stats["total_tokens"] += tokens

    def _add_output_tokens(self, text: str):
        """添加输出token统计"""
        tokens = self._estimate_tokens(text)
        self.token_stats["output_tokens"] += tokens
        self.token_stats["total_tokens"] += tokens

    def _reset_token_stats(self):
        """重置token统计"""
        self.token_stats = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        }

    def _get_token_stats(self) -> dict:
        """获取token统计信息"""
        return self.token_stats.copy()

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

    def _search_searxng(self, query: str) -> dict:
        """调用SearxNG API进行搜索"""
        url = f"{self.valves.SEARXNG_URL}/search"
        
        params = {
            'q': query.strip(),
            'format': 'json',
            'language': self.valves.SEARXNG_LANGUAGE,
            'safesearch': self.valves.SEARXNG_SAFESEARCH,
            'categories': self.valves.SEARXNG_CATEGORIES
        }
        
        if self.valves.SEARXNG_TIME_RANGE:
            params['time_range'] = self.valves.SEARXNG_TIME_RANGE
        
        try:
            if self.valves.DEBUG_MODE:
                print(f"🔍 SearxNG搜索: {query}")
            
            response = requests.get(
                url,
                params=params,
                timeout=self.valves.SEARXNG_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ SearxNG搜索错误: {str(e)}")
            return {"error": str(e)}

    def _call_openai_api(self, system_prompt: str, user_prompt: str, json_mode: bool = False) -> str:
        """调用OpenAI API"""
        if not self.valves.OPENAI_API_KEY:
            return "错误: 未设置OpenAI API密钥"
        
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # 构建消息列表
        messages = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": messages,
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.OPENAI_TEMPERATURE,
        }
        
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        # 添加输入token统计
        if system_prompt and system_prompt.strip():
            self._add_input_tokens(system_prompt)
        self._add_input_tokens(user_prompt)
        
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.valves.OPENAI_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            
            answer = result["choices"][0]["message"]["content"]
            self._add_output_tokens(answer)
            
            return answer
            
        except Exception as e:
            error_msg = f"OpenAI API调用错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            return error_msg

    def _stage1_optimize_query(self, user_message: str, messages: List[dict]) -> str:
        """阶段1: 问题优化"""
        # 提取历史上下文
        context_text = ""
        if messages and len(messages) > 1:
            recent_messages = messages[-self.valves.HISTORY_TURNS*2:] if len(messages) > self.valves.HISTORY_TURNS*2 else messages
            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    context_text += f"用户: {content}\n"
                elif role == "assistant":
                    context_text += f"助手: {content}\n"
        
        system_prompt = ""
        
        user_prompt = f"""我是一个搜索查询优化专家，需要根据用户的历史对话和当前问题，优化搜索查询以获得更好的搜索结果。

优化原则：
1. 提取核心关键词
2. 去除冗余词汇  
3. 保留重要限定词
4. 结合历史上下文理解用户真实意图
5. 确保查询简洁且精准

历史对话上下文:
{context_text if context_text else "无历史对话"}

当前用户问题: {user_message}

请优化这个问题以获得更好的搜索结果，直接返回优化后的查询词，不需要解释。"""

        response = self._call_openai_api(system_prompt, user_prompt)
        
        # 如果优化失败，返回原始问题
        if "错误" in response or not response.strip():
            return user_message
        
        return response.strip()

    def _stage2_search_and_select(self, optimized_query: str) -> List[dict]:
        """阶段2: 搜索并选择最佳结果"""
        search_results = self._search_searxng(optimized_query)
        
        if "error" in search_results or not search_results.get("results"):
            return []
        
        # 处理搜索结果
        all_results = []
        for result in search_results.get("results", []):
            result_info = {
                "title": result.get("title", "").strip(),
                "link": result.get("url", "").strip(),
                "snippet": result.get("content", "").strip(),
                "website_type": self._identify_website_type(result.get("url", "")),
            }
            if result_info["title"] and result_info["link"]:
                all_results.append(result_info)
        
        if not all_results:
            return []
        
        # 如果结果较少，直接返回
        if len(all_results) <= self.valves.SELECTED_URLS_COUNT:
            return all_results
        
        # 使用LLM选择最佳结果
        system_prompt = """你是一个专业的信息筛选专家。你的任务是从搜索结果中选择与用户问题最相关的网站。

核心原则：
1. 相关性是最重要的标准
2. 仔细分析用户问题的核心意图
3. 评估每个搜索结果的标题和摘要是否直接回答用户问题
4. 优先选择内容相关度高的结果"""
        
        results_text = ""
        for i, result in enumerate(all_results):
            results_text += f"[{i}] 标题: {result['title']}\n"
            results_text += f"    链接: {result['link']}\n"
            results_text += f"    摘要: {result['snippet']}\n"
            results_text += f"    网站类型: {result['website_type']}\n\n"

        user_prompt = f"""用户问题: {optimized_query}

请从以下搜索结果中选择{self.valves.SELECTED_URLS_COUNT}个与用户问题最相关的结果。

评估标准：
1. 标题和摘要是否直接回答用户问题（最重要）
2. 内容是否包含问题的关键词和概念

搜索结果:
{results_text}

请以JSON格式返回最相关的{self.valves.SELECTED_URLS_COUNT}个结果的索引：
{{
    "selected_indices": [0, 1, 2, ...]
}}

注意：必须严格按照相关性选择，不要被网站类型影响。"""

        response = self._call_openai_api(system_prompt, user_prompt, json_mode=True)
        
        try:
            selection = json.loads(response)
            selected_indices = selection.get("selected_indices", [])
            selected_results = [all_results[i] for i in selected_indices if 0 <= i < len(all_results)]
            return selected_results[:self.valves.SELECTED_URLS_COUNT]
        except:
            # 如果选择失败，返回前N个结果
            return all_results[:self.valves.SELECTED_URLS_COUNT]

    async def _fetch_url_content(self, session: aiohttp.ClientSession, url: str) -> dict:
        """异步获取网页内容"""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=self.valves.CONTENT_FETCH_TIMEOUT)) as response:
                if response.status == 200:
                    html_content = await response.text()
                    # 使用BeautifulSoup提取文本内容
                    soup = BeautifulSoup(html_content, 'html.parser')
                    
                    # 移除script和style标签
                    for script in soup(["script", "style"]):
                        script.decompose()
                    
                    # 提取主要文本内容
                    text_content = soup.get_text()
                    # 清理文本
                    lines = (line.strip() for line in text_content.splitlines())
                    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                    text_content = ' '.join(chunk for chunk in chunks if chunk)
                    
                    # 限制内容长度
                    if len(text_content) > self.valves.MAX_CONTENT_LENGTH:
                        text_content = text_content[:self.valves.MAX_CONTENT_LENGTH] + "..."
                    
                    return {
                        "url": url,
                        "status": "success",
                        "content": text_content,
                        "title": soup.title.string if soup.title else ""
                    }
                else:
                    return {
                        "url": url,
                        "status": "error",
                        "content": f"HTTP {response.status}",
                        "title": ""
                    }
        except Exception as e:
            return {
                "url": url,
                "status": "error", 
                "content": str(e),
                "title": ""
            }

    async def _stage3_fetch_content(self, selected_results: List[dict]) -> List[dict]:
        """阶段3: 并发获取网页内容"""
        async with aiohttp.ClientSession() as session:
            tasks = []
            for result in selected_results:
                task = self._fetch_url_content(session, result["link"])
                tasks.append(task)
            
            contents = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 处理内容并与原结果合并
            enriched_results = []
            for i, content in enumerate(contents):
                if isinstance(content, dict):
                    enriched_result = selected_results[i].copy()
                    enriched_result.update(content)
                    enriched_results.append(enriched_result)
                else:
                    # 处理异常情况
                    enriched_result = selected_results[i].copy()
                    enriched_result.update({
                        "status": "error",
                        "content": str(content),
                        "title": ""
                    })
                    enriched_results.append(enriched_result)
            
            return enriched_results

    def _stage4_generate_final_answer(self, user_message: str, enriched_results: List[dict], stream: bool = False) -> Union[str, Generator]:
        """阶段4: 生成最终回答"""
        # 构建信息源文本和链接列表
        source_content = ""
        all_sources = []
        successful_sources = []
        
        for i, result in enumerate(enriched_results, 1):
            # 记录所有来源信息
            source_info = {
                "index": i,
                "title": result.get('title', result.get('title', '未知标题')),
                "link": result['link'],
                "website_type": result['website_type'],
                "status": result.get("status", "unknown")
            }
            all_sources.append(source_info)
            
            if result.get("status") == "success" and result.get("content"):
                source_content += f"[来源{i}] {result.get('title', result['title'])}\n"
                source_content += f"链接: {result['link']}\n"
                source_content += f"网站类型: {result['website_type']}\n"
                source_content += f"内容摘要: {result['snippet']}\n"
                source_content += f"主要内容: {result['content']}\n\n"
                successful_sources.append(i)
            else:
                # 即使获取失败，也添加基本信息
                source_content += f"[来源{i}] {result.get('title', result['title'])}\n"
                source_content += f"链接: {result['link']}\n"
                source_content += f"网站类型: {result['website_type']}\n"
                source_content += f"内容摘要: {result.get('snippet', '无摘要')}\n"
                source_content += f"状态: 内容获取失败 - {result.get('content', '未知错误')}\n\n"
        
        if not successful_sources:
            return "抱歉，所有网页内容获取都失败了，无法提供基于网页内容的回答。"
        
        # 构建所有链接的markdown格式
        all_links_md = ""
        for source in all_sources:
            status_indicator = "✅" if source["status"] == "success" else "❌"
            all_links_md += f"{status_indicator} [{source['title']}]({source['link']}) ({source['website_type']})\n"
        
        system_prompt = """你是一个专业的问答助手。你的任务是严格基于用户的问题和提供的信息源来生成回答。

核心原则：
1. 用户问题是唯一的导向 - 严格按照用户问题的要求回答
2. 不要被信息源的内容带偏 - 只提取与用户问题直接相关的信息
3. 如果信息源包含大量无关内容，要有判断能力筛选出相关部分
4. 如果信息源不足以回答用户问题，诚实说明
5. 不要为了使用所有信息源而强行堆砌无关内容

回答质量标准：
- 精准性：回答必须直接针对用户问题
- 相关性：只包含与问题相关的信息
- 完整性：在相关范围内尽可能完整回答
- 诚实性：不编造信息，不确定时说明"""

        user_prompt = f"""用户问题: {user_message}

请严格基于用户问题和以下信息源生成回答。

关键要求：
1. 紧扣用户问题，不要偏离主题
2. 从信息源中筛选出与问题直接相关的内容
3. 忽略信息源中与问题无关的内容（如广告、导航、无关段落等）
4. 只使用能够回答用户问题的信息源，不要强行使用所有源
5. 如果某个信息源与问题无关，可以忽略它
6. 在回答中使用markdown链接格式引用相关来源：[标题](链接)

所有可用来源链接：
{all_links_md}

判断标准：
- 这个信息是否直接回答了用户的问题？
- 这个信息是否对理解答案有帮助？
- 如果答案是"否"，就不要包含这个信息

信息源详情:
{source_content}

请严格基于用户问题生成回答，要求：
1. 只回答与问题直接相关的内容
2. 对相关信息源使用markdown链接格式引用,[标题](链接)
3. 末尾列出实际使用的参考来源
4. 不要为了凑字数而包含无关信息"""

        if stream:
            return self._stream_openai_response(user_prompt, system_prompt)
        else:
            return self._call_openai_api(system_prompt, user_prompt)

    def _stream_openai_response(self, user_prompt: str, system_prompt: str) -> Generator:
        """流式处理OpenAI响应"""
        if not self.valves.OPENAI_API_KEY:
            yield "错误: 未设置OpenAI API密钥"
            return
        
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # 构建消息列表
        messages = []
        if system_prompt and system_prompt.strip():
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": messages,
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.OPENAI_TEMPERATURE,
            "stream": True
        }
        
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=self.valves.OPENAI_TIMEOUT
            )
            response.raise_for_status()
            
            collected_content = ""
            
            for line in response.iter_lines():
                if line:
                    line = line.decode('utf-8')
                    if line.startswith('data: '):
                        data = line[6:]
                        if data == '[DONE]':
                            break
                        try:
                            json_data = json.loads(data)
                            delta = json_data.get('choices', [{}])[0].get('delta', {}).get('content', '')
                            if delta:
                                collected_content += delta
                                self._add_output_tokens(delta)
                                yield delta
                        except json.JSONDecodeError:
                            pass
                            
        except Exception as e:
            error_msg = f"OpenAI流式API调用错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            yield error_msg

    def _emit_processing(self, content: str, stage: str = "processing") -> Generator[dict, None, None]:
        """发送处理过程内容"""
        yield {
            'choices': [{
                'delta': {
                    'processing_content': content + '\n',
                    'processing_title': STAGE_TITLES.get(stage, "处理中"),
                    'processing_stage': STAGE_GROUP.get(stage, "stage_group_1")
                },
                'finish_reason': None
            }]
        }

    def pipe(self, user_message: str, model_id: str, messages: List[dict], body: dict) -> Union[str, Generator, Iterator]:
        """主管道函数"""
        # 重置token统计
        self._reset_token_stats()

        if self.valves.DEBUG_MODE:
            print(f"📝 用户消息: {user_message}")
            print(f"🔧 模型ID: {model_id}")
            print(f"📜 历史消息数量: {len(messages) if messages else 0}")

        # 验证输入
        if not user_message or not user_message.strip():
            yield "❌ 请输入有效的问题或查询内容"
            return

        # 检查是否是流式模式  
        stream_mode = body.get("stream", False) and self.valves.ENABLE_STREAMING
        
        try:
            # 阶段1: 问题优化
            if stream_mode:
                for chunk in self._emit_processing("正在优化搜索问题...", "query_optimization"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield "🔄 **阶段1**: 正在优化搜索问题..."
            
            optimized_query = self._stage1_optimize_query(user_message, messages)
            
            if stream_mode:
                opt_info = f"✅ 问题优化完成\n优化后的问题: {optimized_query}"
                for chunk in self._emit_processing(opt_info, "query_optimization"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield f"✅ 优化后的问题: {optimized_query}\n"

            # 阶段2: 搜索和选择
            if stream_mode:
                for chunk in self._emit_processing("正在进行网络搜索和结果筛选...", "web_search"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield "🔍 **阶段2**: 正在进行网络搜索和结果筛选..."
            
            selected_results = self._stage2_search_and_select(optimized_query)
            
            if not selected_results:
                yield "❌ 未找到相关搜索结果，请尝试其他关键词"
                return
            
            # 展示选中的信息源
            source_info = f"✅ 已选择{len(selected_results)}个信息源:\n"
            for i, result in enumerate(selected_results, 1):
                source_info += f"[{i}] {result['title']} ({result['website_type']})\n    {result['link']}\n"
            
            if stream_mode:
                for chunk in self._emit_processing(source_info, "web_search"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield source_info

            # 阶段3: 获取网页内容
            if stream_mode:
                for chunk in self._emit_processing("正在获取网页内容...", "content_fetch"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield "📄 **阶段3**: 正在获取网页内容..."
            
            # 在同步环境中运行异步代码
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                enriched_results = loop.run_until_complete(self._stage3_fetch_content(selected_results))
            finally:
                loop.close()
            
            # 统计成功获取的内容
            successful_count = sum(1 for r in enriched_results if r.get("status") == "success")
            
            content_info = f"✅ 内容获取完成，成功获取{successful_count}/{len(enriched_results)}个网页内容"
            
            if stream_mode:
                for chunk in self._emit_processing(content_info, "content_fetch"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield content_info

            # 阶段4: 生成最终回答
            if stream_mode:
                # 流式模式开始生成回答的标识
                answer_start_msg = {
                    'choices': [{
                        'delta': {
                            'content': "\n**💭 生成最终回答**\n"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(answer_start_msg)}\n\n"
            else:
                yield "🤖 **阶段4**: 正在基于获取的内容生成回答..."

            # 生成最终回答
            if stream_mode:
                for chunk in self._stage4_generate_final_answer(user_message, enriched_results, stream=True):
                    yield chunk
                # 流式模式结束后添加token统计
                token_info = self._get_token_stats()
                yield f"\n\n---\n📊 **Token统计**: 输入 {token_info['input_tokens']}, 输出 {token_info['output_tokens']}, 总计 {token_info['total_tokens']}"
            else:
                result = self._stage4_generate_final_answer(user_message, enriched_results, stream=False)
                yield result
                # 添加token统计信息
                token_info = self._get_token_stats()
                yield f"\n\n---\n📊 **Token统计**: 输入 {token_info['input_tokens']}, 输出 {token_info['output_tokens']}, 总计 {token_info['total_tokens']}"

        except Exception as e:
            error_msg = f"❌ Pipeline执行错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            yield error_msg