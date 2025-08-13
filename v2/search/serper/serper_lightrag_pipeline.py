"""
编写基于serper API的联网搜索及lightrag问答 pipeline,意图识别json返回
1.定义并识别网站类型
  wiki:url匹配wikipedia
  百度百科:url匹配baike.baidu
  MBA智库百科:wiki.mbalib
  论文:url匹配arxiv,doi,pdf
  其他:url匹配其他
2.阶段1:
    - 根据用户历史问题和当前问题输出优化后的问题(json格式，中英版本):
    {
    "optimized_question_cn": "优化后的问题",
    "optimized_question_en": "优化后的问题(英文)",
    }
    - process展示优化后的问题
3.阶段2:
  - 根据优化后的问题进行联网搜索,中文英文各10个结果
  - 根据结果url识别网站类型(识别不了则为其他),处理为json格式
  - 将20个结果的json输入LLM，让LLM根据问题和结果选择最恰当的10(可配置)个网页地址
  - process展示信息源
4.阶段4:
   - 根据阶段3的10个网页地址进行联网内容获取(协程并发)，获取到的是html
   - LLM进行内容解析，输出json格式
   - process展示信息源
5.阶段5: 根据阶段4的内容和用户的问题进行lightrag问题优化，至少150字，要包含实体，关系，学术词语，丰富内容
6.阶段6: 根据阶段5的优化lightrag问题进行lightrag问答，直接输出最终回答
参考文件:v2\search\serper_openai_pipeline.py
api参考:v2\search\test\serper_test.py
处理参考:v2\search\searxng_lightrag_pipeline.py
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
import concurrent.futures

# 后端阶段标题映射
STAGE_TITLES = {
    "query_optimization": "问题优化",
    "web_search": "网络搜索",
    "content_fetch": "内容获取", 
    "lightrag_query_generation": "LightRAG查询优化",
    "lightrag_answer": "生成最终回答",
}

STAGE_GROUP = {
    "query_optimization": "stage_group_1",
    "web_search": "stage_group_2", 
    "content_fetch": "stage_group_3",
    "lightrag_query_generation": "stage_group_4",
    "lightrag_answer": "stage_group_5",
}

# LightRAG查询生成示例
LIGHTRAG_QUERY_EXAMPLE = """
示例：
用户问题: 护肤品中的烟酰胺有什么作用？

搜索信息:
[信息源1] 烟酰胺的护肤功效及作用机制
网站类型: 百度百科
内容摘要: 烟酰胺是维生素B3的一种形式，在护肤品中具有多种功效
主要内容: 烟酰胺(Niacinamide)，也称为维生素B3或维生素PP，是水溶性维生素。在护肤品中，烟酰胺具有调节皮脂分泌、改善毛孔粗大、提亮肤色、抗氧化等多重功效。研究表明，5%浓度的烟酰胺可以有效减少皮脂分泌量，改善痘痘肌肤状况。烟酰胺还能抑制黑色素向角质细胞转移，从而起到美白效果...

[信息源2] 烟酰胺在化妆品中的应用研究
网站类型: 论文
内容摘要: 详细分析了烟酰胺在各类护肤品中的添加量和效果
主要内容: 烟酰胺作为护肤品的活性成分，其有效浓度通常在2%-10%之间。临床研究显示，含有烟酰胺的护肤品能够显著改善皮肤屏障功能，增加神经酰胺含量，减少经皮水分流失。此外，烟酰胺与其他成分如透明质酸、维生素C等具有良好的配伍性...

生成的查询语句:
我想了解烟酰胺这个成分在护肤领域的具体作用机制，特别是它是如何通过调节皮脂分泌来改善痘痘肌肤的，以及为什么5%的浓度被认为是有效的标准，另外烟酰胺抑制黑色素转移的生物学原理是什么，它与神经酰胺和透明质酸等其他护肤成分的协同作用机制又是怎样的，这些科学研究是如何证实烟酰胺能够同时实现控油、美白、修复皮肤屏障等多重功效的。
"""

class Pipeline:
    class Valves(BaseModel):
        # Serper API配置
        SERPER_API_KEY: str
        SERPER_BASE_URL: str
        SERPER_SEARCH_COUNT: int
        SERPER_TIMEOUT: int
        
        # OpenAI配置
        OPENAI_API_KEY: str
        OPENAI_BASE_URL: str
        OPENAI_MODEL: str
        OPENAI_TIMEOUT: int
        OPENAI_MAX_TOKENS: int
        OPENAI_TEMPERATURE: float
        
        # LightRAG配置
        LIGHTRAG_BASE_URL: str
        LIGHTRAG_DEFAULT_MODE: str
        LIGHTRAG_TIMEOUT: int
        LIGHTRAG_ENABLE_STREAMING: bool
        
        # Pipeline配置
        ENABLE_STREAMING: bool
        DEBUG_MODE: bool
        SELECTED_URLS_COUNT: int
        CONTENT_FETCH_TIMEOUT: int
        MAX_CONTENT_LENGTH: int
        
        # 历史会话配置
        HISTORY_TURNS: int

    def __init__(self):
        self.name = "Serper Search LightRAG Pipeline"
        
        # 初始化token统计
        self.token_stats = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0
        }
        
        self.valves = self.Valves(
            **{
                # Serper API配置
                "SERPER_API_KEY": os.getenv("SERPER_API_KEY", "b981da4c22e8e472ff3840e9e975b5b9827f8795"),
                "SERPER_BASE_URL": os.getenv("SERPER_BASE_URL", "https://google.serper.dev"),
                "SERPER_SEARCH_COUNT": int(os.getenv("SERPER_SEARCH_COUNT", "10")),
                "SERPER_TIMEOUT": int(os.getenv("SERPER_TIMEOUT", "15")),
                
                # OpenAI配置
                "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", ""),
                "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
                "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o"),
                "OPENAI_TIMEOUT": int(os.getenv("OPENAI_TIMEOUT", "60")),
                "OPENAI_MAX_TOKENS": int(os.getenv("OPENAI_MAX_TOKENS", "4000")),
                "OPENAI_TEMPERATURE": float(os.getenv("OPENAI_TEMPERATURE", "0.7")),
                
                # LightRAG配置
                "LIGHTRAG_BASE_URL": os.getenv("LIGHTRAG_BASE_URL", "http://localhost:9621"),
                "LIGHTRAG_DEFAULT_MODE": os.getenv("LIGHTRAG_DEFAULT_MODE", "hybrid"),
                "LIGHTRAG_TIMEOUT": int(os.getenv("LIGHTRAG_TIMEOUT", "30")),
                "LIGHTRAG_ENABLE_STREAMING": os.getenv("LIGHTRAG_ENABLE_STREAMING", "true").lower() == "true",
                
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
        print(f"Serper Search LightRAG Pipeline启动: {__name__}")
        
        # 验证必需的API密钥
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")
        if not self.valves.SERPER_API_KEY:
            print("❌ 缺少Serper API密钥，请设置SERPER_API_KEY环境变量")
            
        # 测试LightRAG连接
        try:
            response = requests.get(f"{self.valves.LIGHTRAG_BASE_URL}/health", timeout=5)
            if response.status_code == 200:
                print("✅ LightRAG服务连接成功")
            else:
                print(f"⚠️ LightRAG服务响应异常: {response.status_code}")
        except Exception as e:
            print(f"❌ 无法连接到LightRAG服务: {e}")

    async def on_shutdown(self):
        print(f"Serper Search LightRAG Pipeline关闭: {__name__}")

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
        else:
            return '其他'

    def _search_serper(self, query: str, gl: str = "cn", hl: str = "zh-cn") -> dict:
        """调用Serper API进行搜索"""
        url = f"{self.valves.SERPER_BASE_URL}/search"
        
        payload = {
            "q": query,
            "num": self.valves.SERPER_SEARCH_COUNT,
            "gl": gl,  # 地理位置
            "hl": hl   # 语言
        }
        
        headers = {
            'X-API-KEY': self.valves.SERPER_API_KEY,
            'Content-Type': 'application/json'
        }
        
        try:
            if self.valves.DEBUG_MODE:
                print(f"🔍 Serper搜索: {query} (gl={gl}, hl={hl})")
            
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.SERPER_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ Serper搜索错误: {str(e)}")
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
        
        # 构建消息列表，只有system_prompt不为空时才添加system消息
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

    def _stage1_optimize_query(self, user_message: str, messages: List[dict]) -> dict:
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

请将优化后的问题以JSON格式返回，包含中文和英文版本：
{{
    "optimized_question_cn": "优化后的中文问题",
    "optimized_question_en": "optimized English question"
}}

优化和输出原则：
1. 提取核心关键词
2. 去除冗余词汇
3. 保留重要限定词
4. 结合历史上下文理解用户真实意图
5. 英文版本应该是准确的翻译并适合搜索
6. 输出json格式,不要有任何其他内容

历史对话上下文:
{context_text if context_text else "无历史对话"}

当前用户问题: {user_message}

请优化这个问题以获得更好的搜索结果。"""

        response = self._call_openai_api(system_prompt, user_prompt, json_mode=True)
        
        try:
            return json.loads(response)
        except:
            # 如果JSON解析失败，返回原始问题
            return {
                "optimized_question_cn": user_message,
                "optimized_question_en": user_message
            }

    def _stage2_search_and_select(self, optimized_queries: dict) -> List[dict]:
        """阶段2: 搜索并选择最佳结果"""
        all_results = []
        
        # 中文搜索
        cn_results = self._search_serper(optimized_queries["optimized_question_cn"], gl="cn", hl="zh-cn")
        if "organic" in cn_results:
            for result in cn_results["organic"]:
                result_info = {
                    "title": result.get("title", ""),
                    "link": result.get("link", ""),
                    "snippet": result.get("snippet", ""),
                    "website_type": self._identify_website_type(result.get("link", "")),
                    "search_lang": "zh-cn"
                }
                all_results.append(result_info)
        
        # 英文搜索
        en_results = self._search_serper(optimized_queries["optimized_question_en"], gl="us", hl="en")
        if "organic" in en_results:
            for result in en_results["organic"]:
                result_info = {
                    "title": result.get("title", ""),
                    "link": result.get("link", ""),
                    "snippet": result.get("snippet", ""),
                    "website_type": self._identify_website_type(result.get("link", "")),
                    "search_lang": "en"
                }
                all_results.append(result_info)
        
        if not all_results:
            return []
        
        # 使用LLM选择最佳结果
        system_prompt = ""

        results_text = ""
        for i, result in enumerate(all_results):
            results_text += f"[{i}] 标题: {result['title']}\n"
            results_text += f"    链接: {result['link']}\n"
            results_text += f"    摘要: {result['snippet']}\n"
            results_text += f"    网站类型: {result['website_type']}\n"
            results_text += f"    搜索语言: {result['search_lang']}\n\n"

        user_prompt = f"""我是一个信息筛选专家，需要根据用户的问题和搜索结果，选择最相关、最有价值的{self.valves.SELECTED_URLS_COUNT}个网页链接。

请以JSON格式返回选中的结果索引（从0开始）：
{{
    "selected_indices": [0, 1, 2, ...]
}}

选择标准：
1. 内容与问题的相关性
2. 信息源的权威性（wiki、百科类优先）
3. 内容的丰富程度
4. 避免重复内容

用户问题: {optimized_queries["optimized_question_cn"]}

搜索结果:
{results_text}

请选择最相关的{self.valves.SELECTED_URLS_COUNT}个结果。"""

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

    async def _stage4_fetch_content(self, selected_results: List[dict]) -> List[dict]:
        """阶段4: 并发获取网页内容"""
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

    def _stage5_generate_lightrag_query(self, user_message: str, enriched_results: List[dict]) -> str:
        """阶段5: 根据阶段4的内容和用户的问题进行lightrag问题优化"""
        # 构建信息源文本
        source_content = ""
        successful_sources = []
        
        for i, result in enumerate(enriched_results, 1):
            if result.get("status") == "success" and result.get("content"):
                source_content += f"[信息源{i}] {result.get('title', '未知标题')}\n"
                source_content += f"网站类型: {result['website_type']}\n"
                source_content += f"内容摘要: {result['snippet']}\n"
                source_content += f"主要内容: {result['content'][:3000]}...\n\n"
                successful_sources.append(i)
        
        if not successful_sources:
            return f"基于搜索信息回答：{user_message}"
        
        system_prompt = ""

        user_prompt = f"""我是一个专业的问题优化专家，需要根据用户的问题和搜索到的信息，生成一个自然、深入的查询语句，就像一个好奇的专家在思考和提问一样。

要求：
1. 语言自然流畅，像人在思考时的表达方式，不要分条列点
2. 从搜索信息中自行识别并包含具体的名词、实体、专业术语
3. 围绕用户问题的核心关注点，不要涉及无关角度
4. 长度至少150字，体现思考的深度
5. 直接输出一段连贯的查询文字，不使用任何格式化标记

{LIGHTRAG_QUERY_EXAMPLE}

现在请处理以下实际问题：

用户问题: {user_message}

搜索到的信息内容:
{source_content}

请参考上面的示例，基于用户的问题和这些搜索信息，生成一个自然、深入的查询语句。要像一个专家在思考这个问题时的表达方式，从搜索信息中自行识别并使用相关的具体实体和名词，紧扣问题核心，不要分点或使用格式化。

直接输出查询语句："""

        response = self._call_openai_api(system_prompt, user_prompt)
        
        # 确保生成的查询符合最小长度要求
        if len(response) < 150:
            # 如果太短，尝试重新生成一个更自然的查询
            fallback_system = ""
            fallback_user = f"我是一个专业的问题优化专家，需要生成一个自然、深入的查询语句，像专家在思考问题时的表达方式。\n\n针对'{user_message}'这个问题，请结合搜索到的相关信息，生成一个至少150字的自然查询语句，要包含具体的专业术语和概念，体现深度思考，不要分条列点。"
            fallback_response = self._call_openai_api(fallback_system, fallback_user)
            return fallback_response if len(fallback_response) >= 150 else f"我想深入理解{user_message}这个问题，特别是通过刚才搜索获得的这些资料，来全面掌握相关的核心概念、专业术语和内在机制，希望能够从多个层面来分析和理解这个主题的本质特征和重要意义。"
        
        return response

    def _query_lightrag_standard(self, query: str, mode: str) -> dict:
        """标准LightRAG查询API"""
        url = f"{self.valves.LIGHTRAG_BASE_URL}/query"
        payload = {
            "query": query,
            "mode": mode
        }

        headers = {"Content-Type": "application/json"}
        
        # 统计LightRAG查询的输入token
        self._add_input_tokens(query)

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.LIGHTRAG_TIMEOUT
            )
            response.raise_for_status()
            result = response.json()
            
            # 统计LightRAG响应的输出token
            if "response" in result:
                self._add_output_tokens(result["response"])
                
            return result
        except Exception as e:
            return {"error": f"查询失败: {str(e)}"}

    def _query_lightrag_streaming(self, query: str, mode: str) -> Generator[str, None, None]:
        """流式LightRAG查询API"""
        url = f"{self.valves.LIGHTRAG_BASE_URL}/query/stream"

        payload = {
            "query": query,
            "mode": mode
        }

        headers = {"Content-Type": "application/json"}
        
        # 统计LightRAG查询的输入token
        self._add_input_tokens(query)

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                stream=True,
                timeout=self.valves.LIGHTRAG_TIMEOUT
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    line_text = line.decode('utf-8').strip()
                    if line_text:
                        try:
                            data = json.loads(line_text)
                            if 'response' in data and data['response']:
                                chunk = data['response']
                                # 统计LightRAG流式输出token
                                self._add_output_tokens(chunk)
                                yield chunk
                            elif 'error' in data:
                                error_msg = data['error']
                                yield f"错误: {error_msg}"
                        except json.JSONDecodeError:
                            continue

        except Exception as e:
            error_msg = f"LightRAG流式查询失败: {str(e)}"
            yield error_msg

    def _stage6_query_lightrag(self, lightrag_query: str, stream: bool = False) -> Union[str, Generator]:
        """阶段6: 根据阶段5的优化lightrag问题进行lightrag问答"""
        mode = self.valves.LIGHTRAG_DEFAULT_MODE

        if stream and self.valves.LIGHTRAG_ENABLE_STREAMING:
            return self._query_lightrag_streaming(lightrag_query, mode)
        else:
            result = self._query_lightrag_standard(lightrag_query, mode)
            if "error" in result:
                return f"LightRAG查询失败: {result['error']}"
            return result.get("response", "未获取到响应内容")

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
        
        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
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
            
            optimized_queries = self._stage1_optimize_query(user_message, messages)
            
            if stream_mode:
                opt_info = f"✅ 问题优化完成\n中文: {optimized_queries['optimized_question_cn']}\n英文: {optimized_queries['optimized_question_en']}"
                for chunk in self._emit_processing(opt_info, "query_optimization"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield f"✅ 中文优化问题: {optimized_queries['optimized_question_cn']}\n"
                yield f"✅ 英文优化问题: {optimized_queries['optimized_question_en']}\n"

            # 阶段2: 搜索和选择
            if stream_mode:
                for chunk in self._emit_processing("正在进行网络搜索和结果筛选...", "web_search"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield "🔍 **阶段2**: 正在进行网络搜索和结果筛选..."
            
            selected_results = self._stage2_search_and_select(optimized_queries)
            
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

            # 阶段4: 获取网页内容 (使用异步)
            if stream_mode:
                for chunk in self._emit_processing("正在获取网页内容...", "content_fetch"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield "📄 **阶段4**: 正在获取网页内容..."
            
            # 在同步环境中运行异步代码
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                enriched_results = loop.run_until_complete(self._stage4_fetch_content(selected_results))
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

            # 阶段5: 生成LightRAG优化查询
            if stream_mode:
                for chunk in self._emit_processing("正在生成LightRAG优化查询...", "lightrag_query_generation"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield "🧠 **阶段5**: 正在生成LightRAG优化查询..."

            lightrag_query = self._stage5_generate_lightrag_query(user_message, enriched_results)
            
            lightrag_info = f"✅ LightRAG查询生成完成\n查询内容: {lightrag_query[:200]}{'...' if len(lightrag_query) > 200 else ''}"
            
            if stream_mode:
                for chunk in self._emit_processing(lightrag_info, "lightrag_query_generation"):
                    yield f'data: {json.dumps(chunk)}\n\n'
            else:
                yield lightrag_info

            # 阶段6: LightRAG问答
            if stream_mode:
                # 流式模式开始生成回答的标识
                answer_start_msg = {
                    'choices': [{
                        'delta': {
                            'content': "\n**💭 LightRAG最终回答**\n"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(answer_start_msg)}\n\n"
                
                # 流式生成LightRAG回答
                lightrag_result = self._stage6_query_lightrag(lightrag_query, stream=True)
                if isinstance(lightrag_result, str):
                    # 非流式结果
                    chunk_msg = {
                        'choices': [{
                            'delta': {
                                'content': lightrag_result
                            },
                            'finish_reason': None
                        }]
                    }
                    yield f"data: {json.dumps(chunk_msg)}\n\n"
                else:
                    # 流式结果
                    for chunk in lightrag_result:
                        chunk_msg = {
                            'choices': [{
                                'delta': {
                                    'content': chunk
                                },
                                'finish_reason': None
                            }]
                        }
                        yield f"data: {json.dumps(chunk_msg)}\n\n"
                
                # 流式模式结束后添加token统计
                token_info = self._get_token_stats()
                token_msg = {
                    'choices': [{
                        'delta': {
                            'content': f"\n\n---\n📊 **Token统计**: 输入 {token_info['input_tokens']}, 输出 {token_info['output_tokens']}, 总计 {token_info['total_tokens']}"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(token_msg)}\n\n"
            else:
                yield "🤖 **阶段6**: 正在基于优化查询进行LightRAG问答..."
                result = self._stage6_query_lightrag(lightrag_query, stream=False)
                yield result
                # 添加token统计信息
                token_info = self._get_token_stats()
                yield f"\n\n---\n📊 **Token统计**: 输入 {token_info['input_tokens']}, 输出 {token_info['output_tokens']}, 总计 {token_info['total_tokens']}"

        except Exception as e:
            error_msg = f"❌ Pipeline执行错误: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"❌ {error_msg}")
            yield error_msg