"""
title: 专业领域智能意图识别管道
author: open-webui
date: 2024-12-20
version: 1.0
license: MIT
description: 可配置的专业领域智能意图识别5阶段管道：1) 专业意图识别判断，2) 专业查询优化，3) 网络搜索，4) 生成增强LightRAG查询，5) LightRAG专业问答。默认配置为化妆品与化学原料领域，可通过环境变量自定义其他专业领域。
requirements: requests, pydantic
"""

import os
import json
import requests
import time
from typing import List, Union, Generator, Iterator
from pydantic import BaseModel


class Pipeline:
    class Valves(BaseModel):
        # SearxNG搜索API配置
        SEARXNG_URL: str
        SEARXNG_SEARCH_COUNT: int
        SEARXNG_LANGUAGE: str
        SEARXNG_TIMEOUT: int
        SEARXNG_CATEGORIES: str
        SEARXNG_TIME_RANGE: str
        SEARXNG_SAFESEARCH: int

        # OpenAI配置（用于意图识别、问题优化和LightRAG查询生成）
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
        INTENT_CONFIDENCE_THRESHOLD: float
        PROFESSIONAL_DOMAIN: str
        DOMAIN_DESCRIPTION: str

    def __init__(self):
        # 先设置默认名称，稍后会在valves初始化后更新
        self.name = "专业领域智能意图识别管道"
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
                "SEARXNG_SEARCH_COUNT": int(os.getenv("SEARXNG_SEARCH_COUNT", "8")),
                "SEARXNG_LANGUAGE": os.getenv("SEARXNG_LANGUAGE", "zh-CN"),
                "SEARXNG_TIMEOUT": int(os.getenv("SEARXNG_TIMEOUT", "15")),
                "SEARXNG_CATEGORIES": os.getenv("SEARXNG_CATEGORIES", "general"),
                "SEARXNG_TIME_RANGE": os.getenv("SEARXNG_TIME_RANGE", "month"),  # day, week, month, year
                "SEARXNG_SAFESEARCH": int(os.getenv("SEARXNG_SAFESEARCH", "0")),  # 0, 1, 2

                # OpenAI配置
                "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY", "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"),
                "OPENAI_BASE_URL": os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1"),
                "OPENAI_MODEL": os.getenv("OPENAI_MODEL", "gpt-4o"),
                "OPENAI_TIMEOUT": int(os.getenv("OPENAI_TIMEOUT", "60")),
                "OPENAI_MAX_TOKENS": int(os.getenv("OPENAI_MAX_TOKENS", "4000")),
                "OPENAI_TEMPERATURE": float(os.getenv("OPENAI_TEMPERATURE", "0.7")),

                # LightRAG配置
                "LIGHTRAG_BASE_URL": os.getenv("LIGHTRAG_BASE_URL", "http://117.50.252.245:9621"),
                "LIGHTRAG_DEFAULT_MODE": os.getenv("LIGHTRAG_DEFAULT_MODE", "hybrid"),
                "LIGHTRAG_TIMEOUT": int(os.getenv("LIGHTRAG_TIMEOUT", "30")),
                "LIGHTRAG_ENABLE_STREAMING": os.getenv("LIGHTRAG_ENABLE_STREAMING", "true").lower() == "true",

                # Pipeline配置
                "ENABLE_STREAMING": os.getenv("ENABLE_STREAMING", "true").lower() == "true",
                "DEBUG_MODE": os.getenv("DEBUG_MODE", "false").lower() == "true",
                "INTENT_CONFIDENCE_THRESHOLD": float(os.getenv("INTENT_CONFIDENCE_THRESHOLD", "0.8")),
                "PROFESSIONAL_DOMAIN": os.getenv("PROFESSIONAL_DOMAIN", "化妆品、化学原料"),
                "DOMAIN_DESCRIPTION": os.getenv("DOMAIN_DESCRIPTION", "化妆品、化学原料、配方开发、法规合规、市场应用"),
            }
        )
        
        # 根据配置的专业领域更新系统名称
        self.name = f"{self.valves.PROFESSIONAL_DOMAIN}智能意图识别管道"

    async def on_startup(self):
        print(f"🧪 {self.valves.PROFESSIONAL_DOMAIN}智能意图识别管道启动: {__name__}")

        # 验证必需的API密钥
        if not self.valves.OPENAI_API_KEY:
            print("❌ 缺少OpenAI API密钥，请设置OPENAI_API_KEY环境变量")

        # 测试SearxNG API连接
        try:
            print("🔧 开始测试SearxNG API连接...")
            test_response = self._search_searxng(f"{self.valves.PROFESSIONAL_DOMAIN}测试", count=1)
            if test_response and "results" in test_response:
                print("✅ SearxNG搜索API连接成功")
            else:
                print("⚠️ SearxNG搜索API测试失败")
        except Exception as e:
            print(f"❌ SearxNG搜索API连接失败: {e}")

        # 测试LightRAG连接
        try:
            response = requests.get(f"{self.valves.LIGHTRAG_BASE_URL}/health", timeout=5)
            if response.status_code == 200:
                print("✅ LightRAG知识库服务连接成功")
            else:
                print(f"⚠️ LightRAG知识库服务响应异常: {response.status_code}")
        except Exception as e:
            print(f"❌ 无法连接到LightRAG知识库服务: {e}")

        print(f"🧪 {self.valves.PROFESSIONAL_DOMAIN}专业管道初始化完成")

    async def on_shutdown(self):
        print(f"🧪 {self.valves.PROFESSIONAL_DOMAIN}智能意图识别管道关闭: {__name__}")

    def _estimate_tokens(self, text: str) -> int:
        """
        简单的token估算函数，基于字符数估算
        中文字符按1个token计算，英文单词按平均1.3个token计算
        """
        if not text:
            return 0

        # 统计中文字符数
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')

        # 统计英文单词数（简单按空格分割）
        english_text = ''.join(char if not ('\u4e00' <= char <= '\u9fff') else ' ' for char in text)
        english_words = len([word for word in english_text.split() if word.strip()])

        # 估算token数：中文字符1:1，英文单词1:1.3
        estimated_tokens = chinese_chars + int(english_words * 1.3)

        return max(estimated_tokens, 1)  # 至少返回1个token

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

    def _search_searxng(self, query: str, count: int = None, max_retries: int = 2) -> dict:
        """调用SearxNG API进行搜索，带重试机制"""
        url = f"{self.valves.SEARXNG_URL}/search"

        # 参数验证
        search_count = count or self.valves.SEARXNG_SEARCH_COUNT
        if search_count < 1:
            search_count = 1

        # 构建请求参数
        params = {
            'q': query.strip(),
            'format': 'json',
            'language': self.valves.SEARXNG_LANGUAGE,
            'safesearch': self.valves.SEARXNG_SAFESEARCH,
            'categories': self.valves.SEARXNG_CATEGORIES
        }

        # 添加可选参数
        if self.valves.SEARXNG_TIME_RANGE:
            params['time_range'] = self.valves.SEARXNG_TIME_RANGE

        # 重试逻辑
        for attempt in range(max_retries + 1):
            try:
                if self.valves.DEBUG_MODE:
                    print(f"🔍 SearxNG搜索调试信息 (尝试 {attempt + 1}/{max_retries + 1}):")
                    print(f"   URL: {url}")
                    print(f"   请求参数: {json.dumps(params, ensure_ascii=False, indent=2)}")

                response = requests.get(
                    url,
                    params=params,
                    timeout=self.valves.SEARXNG_TIMEOUT
                )

                if self.valves.DEBUG_MODE:
                    print(f"   响应状态码: {response.status_code}")
                    if response.status_code != 200:
                        print(f"   响应内容: {response.text}")

                response.raise_for_status()
                result = response.json()

                if self.valves.DEBUG_MODE:
                    print(f"   响应成功，数据长度: {len(str(result))}")
                    if isinstance(result, dict):
                        print(f"   找到结果数量: {result.get('number_of_results', 0)}")

                return result

            except requests.exceptions.Timeout:
                if attempt < max_retries:
                    if self.valves.DEBUG_MODE:
                        print(f"⚠️ 搜索超时，{2}秒后重试 (尝试 {attempt + 1}/{max_retries + 1})")
                    time.sleep(2)
                    continue
                else:
                    error_msg = "SearxNG搜索超时，可能是搜索引擎连接问题，请稍后重试"
                    if self.valves.DEBUG_MODE:
                        print(f"❌ {error_msg}")
                    return {"error": error_msg}
            except Exception as e:
                if attempt < max_retries:
                    if self.valves.DEBUG_MODE:
                        print(f"⚠️ 搜索出错，{2}秒后重试: {str(e)}")
                    time.sleep(2)
                    continue
                else:
                    break

        return {"error": "SearxNG搜索失败，请稍后重试"}

    def _format_search_results(self, search_response: dict) -> str:
        """格式化搜索结果为文本"""
        if "error" in search_response:
            return f"搜索错误: {search_response['error']}"

        if not isinstance(search_response, dict):
            return "搜索响应格式错误"

        results = search_response.get("results", [])
        if not results:
            return "未找到相关搜索结果，请尝试其他关键词"

        formatted_results = []
        display_count = min(len(results), self.valves.SEARXNG_SEARCH_COUNT)

        for i, result in enumerate(results[:display_count], 1):
            title = result.get("title", "无标题").strip()
            url = result.get("url", "").strip()
            content = result.get("content", "").strip()

            if content:
                content = ' '.join(content.split())
                if len(content) > 200:
                    content = content[:200] + "..."

            result_text = f"{i}. {title}\n"
            if url:
                result_text += f"   链接: {url}\n"
            if content:
                result_text += f"   内容: {content}\n"

            formatted_results.append(result_text)

        return "\n".join(formatted_results)

    def _extract_search_links(self, search_response: dict) -> str:
        """提取搜索结果中的链接，格式化为MD格式"""
        if "error" in search_response:
            return ""

        results = search_response.get("results", [])
        if not results:
            return ""

        formatted_links = []
        display_count = min(len(results), self.valves.SEARXNG_SEARCH_COUNT)

        for i, result in enumerate(results[:display_count], 1):
            title = result.get("title", "无标题").strip()
            url = result.get("url", "").strip()

            if url and title:
                formatted_links.append(f"{i}. [{title}]({url})")

        return "\n".join(formatted_links)

    def _call_openai_api(self, messages: List[dict], stream: bool = False) -> Union[dict, Iterator[dict]]:
        """调用OpenAI API"""
        url = f"{self.valves.OPENAI_BASE_URL}/chat/completions"

        # 统计输入token
        input_text = ""
        for message in messages:
            input_text += message.get("content", "") + " "
        self._add_input_tokens(input_text)

        headers = {
            "Authorization": f"Bearer {self.valves.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.valves.OPENAI_MODEL,
            "messages": messages,
            "max_tokens": self.valves.OPENAI_MAX_TOKENS,
            "temperature": self.valves.OPENAI_TEMPERATURE,
            "stream": stream
        }

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.OPENAI_TIMEOUT,
                stream=stream
            )
            response.raise_for_status()

            if stream:
                return self._parse_stream_response_with_tokens(response)
            else:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    output_content = result['choices'][0]['message']['content']
                    self._add_output_tokens(output_content)
                return result

        except Exception as e:
            raise Exception(f"OpenAI API调用失败: {str(e)}")

    def _parse_stream_response_with_tokens(self, response) -> Iterator[dict]:
        """解析流式响应并统计token"""
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    data = line[6:]
                    if data.strip() == '[DONE]':
                        break
                    try:
                        chunk = json.loads(data)
                        if 'choices' in chunk and len(chunk['choices']) > 0:
                            delta = chunk['choices'][0].get('delta', {})
                            if 'content' in delta:
                                self._add_output_tokens(delta['content'])
                        yield chunk
                    except json.JSONDecodeError:
                        continue

    def _stage1_intent_recognition(self, user_query: str, messages: List[dict]) -> tuple[str, bool, bool]:
        """第一阶段：意图识别判断"""
        # 构建对话历史
        context_text = ""
        if messages and len(messages) > 1:
            recent_messages = messages[-6:]
            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    context_text += f"用户: {content}\n"
                elif role == "assistant":
                    context_text += f"助手: {content}\n"

        context_info = f"""
**对话历史**:
{context_text.strip() if context_text.strip() else "无历史对话"}

**当前问题**: {user_query}
"""

        intent_messages = [{
            "role": "system",
            "content": f"""你是一个专业的{self.valves.PROFESSIONAL_DOMAIN}领域的意图识别专家。你需要分析用户的问题，判断最佳的处理策略。

**领域背景**：{self.valves.DOMAIN_DESCRIPTION}

**判断标准**：

1. **直接回答类**：基于专业知识可以直接回答的问题
   - 化学原料的基本性质、分子结构、作用机理
   - 化妆品配方的基础理论、配伍原则
   - 常见化学反应、稳定性原理
   - 产品分类、功效机制的解释
   - 基础的法规要求、标准流程
   - 一般性的配方建议和技术指导
   - 化学计算、浓度换算等

2. **需要搜索类**：需要最新、具体、实时信息的问题
   - 最新的法规变化、政策更新
   - 特定品牌产品的详细信息、上市情况
   - 最新的市场趋势、行业动态
   - 具体供应商信息、价格行情
   - 最新的研究成果、技术突破
   - 特定时间的事件、新闻
   - 最新的安全警告、召回信息
   - 当前的认证状态、注册情况

3. **需要知识库类**：需要专业文档和深度分析的问题
   - 复杂配方的设计与优化
   - 多成分间的相互作用分析
   - 产品稳定性和兼容性评估
   - 深度的安全性评价和风险分析
   - 专业技术文档的查询和解读
   - 复杂的法规合规性分析
   - 产品开发全流程的指导
   - 需要关联多个专业领域的综合分析

**判断原则**：
- 优先考虑专业性和准确性
- 对于安全性相关问题，倾向于使用知识库进行深度分析
- 对于实时变化的信息，优先选择搜索
- 对于基础理论问题，可以直接回答

请严格按照以下JSON格式回答：
{{
    "intent": "direct_answer|need_search|need_knowledge_base",
    "confidence": 0.0-1.0,
    "reasoning": "判断原因（说明为什么选择此策略）",
    "direct_answer": "如果选择direct_answer，请提供专业的答案；否则为空字符串"
}}"""
        }, {
            "role": "user",
            "content": context_info
        }]

        try:
            response = self._call_openai_api(intent_messages, stream=False)
            content = response['choices'][0]['message']['content'].strip()
            
            # 尝试解析JSON响应
            try:
                intent_result = json.loads(content)
                intent_type = intent_result.get("intent", "need_search")
                confidence = intent_result.get("confidence", 0.5)
                reasoning = intent_result.get("reasoning", "无法确定意图")
                direct_answer = intent_result.get("direct_answer", "")
                
                if self.valves.DEBUG_MODE:
                    print(f"🧠 意图识别结果: {intent_type} (置信度: {confidence})")
                    print(f"   原因: {reasoning}")
                
                # 基于置信度和意图类型决定处理策略
                if intent_type == "direct_answer" and confidence >= self.valves.INTENT_CONFIDENCE_THRESHOLD:
                    return direct_answer, True, False  # 直接回答
                elif intent_type == "need_knowledge_base":
                    return reasoning, False, True  # 需要知识库
                else:
                    return reasoning, False, False  # 需要搜索
                    
            except json.JSONDecodeError:
                if self.valves.DEBUG_MODE:
                    print(f"⚠️ 意图识别响应解析失败，默认使用搜索: {content}")
                return "响应解析失败，使用搜索策略", False, False
                
        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ 意图识别失败: {e}")
            return "意图识别失败，使用搜索策略", False, False

    def _stage2_optimize_query(self, user_query: str, messages: List[dict]) -> str:
        """第二阶段：基于对话历史的问题优化"""
        context_messages = []

        if messages and len(messages) > 1:
            recent_messages = messages[-8:]
            context_text = ""
            conversation_topics = []

            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    context_text += f"用户: {content}\n"
                    if len(content) > 10:
                        conversation_topics.append(content[:50])
                elif role == "assistant":
                    context_text += f"助手: {content}\n"

            if context_text.strip():
                topics_summary = "、".join(conversation_topics[-3:]) if conversation_topics else "无特定主题"

                context_messages.append({
                    "role": "user",
                    "content": f"""请基于完整的对话历史和当前问题，生成一个优化的{self.valves.PROFESSIONAL_DOMAIN}专业搜索查询。

**对话历史**:
{context_text.strip()}

**对话主题总结**: {topics_summary}

**当前问题**: {user_query}

**专业领域优化任务**:
请深度分析对话历史，理解用户在{self.valves.PROFESSIONAL_DOMAIN}领域的具体需求，然后生成一个专业的搜索查询：

1. **专业上下文理解**：
   - 识别涉及的化学原料、化妆品成分、配方类型
   - 分析用户关注的技术方向（功效、安全性、法规等）
   - 理解用户的专业背景和应用场景

2. **专业查询优化策略**：
   - 使用准确的化学名称、INCI名称、CAS号
   - 补充相关的专业术语（如：表面活性剂、防腐剂、抗氧化剂）
   - 考虑法规分类（如：化妆品法规、REACH法规）
   - 包含相关的应用领域（护肤、彩妆、洗护等）
   - 考虑时间敏感性（最新法规、新品上市等）

3. **输出要求**：
   - 生成一个专业且精准的搜索查询
   - 长度控制在10-50字之间
   - 使用准确的专业术语
   - 只返回优化后的查询文本，不要解释

**优化后的搜索查询**:"""
                })

        if not context_messages:
            context_messages.append({
                "role": "user",
                "content": f"""请优化以下{self.valves.PROFESSIONAL_DOMAIN}领域的搜索查询，使其更专业和精准：

**原始问题**: {user_query}

**专业优化要求**:
1. 补充准确的化学名称、INCI名称、CAS号等专业标识
2. 使用规范的专业术语（如：表面活性剂、乳化剂、防腐剂、抗氧化剂等）
3. 考虑相关的法规分类（化妆品法规、REACH法规、FDA规定等）
4. 包含应用领域信息（护肤、彩妆、洗护、香氛等）
5. 考虑功效机制、安全性、稳定性等关键维度
6. 保持查询简洁但信息丰富
7. 只返回优化后的查询文本，不要解释

**优化后的搜索查询**:"""
            })

        try:
            response = self._call_openai_api(context_messages, stream=False)
            optimized_query = response['choices'][0]['message']['content'].strip()

            if not optimized_query or len(optimized_query) < 3:
                optimized_query = user_query

            if self.valves.DEBUG_MODE:
                print(f"🔧 查询优化: '{user_query}' → '{optimized_query}'")

            return optimized_query

        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ 查询优化失败: {e}")
            return user_query

    def _stage3_search(self, optimized_query: str) -> tuple[str, str, str]:
        """第三阶段：搜索"""
        search_response = self._search_searxng(optimized_query)
        search_results = self._format_search_results(search_response)
        search_links = self._extract_search_links(search_response)

        if "搜索错误" in search_results or "未找到相关搜索结果" in search_results:
            search_status = f"⚠️ {search_results}"
        else:
            search_status = "✅ 搜索完成，找到相关信息"
            if search_links:
                search_status += f"\n\n**相关链接：**\n{search_links}"

        return search_results, search_status, search_links

    def _stage4_generate_lightrag_query(self, original_query: str, search_results: str, messages: List[dict]) -> str:
        """第四阶段：根据搜索结果和对话历史生成增强的LightRAG查询"""
        context_text = ""
        conversation_summary = ""

        if messages and len(messages) > 1:
            recent_messages = messages[-8:]

            for msg in recent_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    context_text += f"用户: {content}\n"
                elif role == "assistant":
                    context_text += f"助手: {content}\n"

            if context_text.strip():
                conversation_summary = f"""
基于对话历史，用户可能关注的主题和背景：
{context_text.strip()}

这表明用户在此次对话中的关注点和需求背景。"""

        context_analysis = conversation_summary if conversation_summary else "\n这是用户的首次提问，没有前序对话历史。"

        prompt_content = f"""你是一个专业的{self.valves.PROFESSIONAL_DOMAIN}领域知识图谱查询专家。请基于以下完整信息生成一个详细、精细、带深度思考的LightRAG检索问题。

**当前用户问题**: {original_query}

**网络搜索获得的最新信息**:
{search_results}

**对话上下文分析**:{context_analysis}

**专业领域任务要求**:
请综合分析以上三个方面的信息，生成一个高质量的{self.valves.PROFESSIONAL_DOMAIN}专业LightRAG查询：

1. **深度理解专业需求**：
   - 识别涉及的化学原料、化妆品成分、配方体系
   - 理解用户关注的技术维度（功效、安全性、稳定性、法规合规性等）
   - 分析用户的专业背景和实际应用场景
   - 考虑产品开发、配方优化、质量控制等具体需求

2. **充分利用专业信息**：
   - 提取化学名称、INCI名称、CAS号等专业标识
   - 识别相关的法规要求、安全评估、技术标准
   - 分析原料供应商、产品规格、市场动态等信息
   - 关注成分间的相互作用、配伍禁忌、稳定性影响

3. **构建专业综合查询**：
   - 将用户问题、搜索信息和专业背景有机结合
   - 生成一个涵盖多个专业维度的详细查询
   - 查询应该能够引导LightRAG进行深度的专业分析和推理
   - 包含具体的应用指导和实践建议

4. **查询格式要求**：
   - 长度控制在150-400字之间
   - 包含具体的化学名称、专业术语和分析角度
   - 体现专业的思考过程和逻辑推理
   - 语言专业准确，逻辑清晰
   - 考虑安全性、合规性、实用性等关键因素

**请直接输出生成的LightRAG查询，不要包含其他解释文字**："""

        query_messages = [{
            "role": "user",
            "content": prompt_content
        }]

        try:
            response = self._call_openai_api(query_messages, stream=False)
            lightrag_query = response['choices'][0]['message']['content'].strip()

            if not lightrag_query or len(lightrag_query) < 20:
                lightrag_query = f"基于以下搜索信息回答问题：{original_query}\n\n搜索结果：{search_results[:500]}..."

            if self.valves.DEBUG_MODE:
                print(f"🔧 LightRAG查询生成: {lightrag_query[:100]}...")

            return lightrag_query

        except Exception as e:
            if self.valves.DEBUG_MODE:
                print(f"❌ LightRAG查询生成失败: {e}")
            return f"基于以下搜索信息回答问题：{original_query}\n\n搜索结果：{search_results[:500]}..."

    def _stage5_query_lightrag(self, lightrag_query: str, stream: bool = False) -> Union[str, Generator[str, None, None]]:
        """第五阶段：使用LightRAG进行问答"""
        mode = self.valves.LIGHTRAG_DEFAULT_MODE

        # 统计LightRAG查询的输入token
        self._add_input_tokens(lightrag_query)

        if stream and self.valves.LIGHTRAG_ENABLE_STREAMING:
            return self._query_lightrag_streaming(lightrag_query, mode)
        else:
            result = self._query_lightrag_standard(lightrag_query, mode)
            if "error" in result:
                return f"LightRAG查询失败: {result['error']}"
            response_content = result.get("response", "未获取到响应内容")
            # 统计LightRAG响应的输出token
            self._add_output_tokens(response_content)
            return response_content

    def _query_lightrag_standard(self, query: str, mode: str) -> dict:
        """标准LightRAG查询API"""
        url = f"{self.valves.LIGHTRAG_BASE_URL}/query"
        payload = {
            "query": query,
            "mode": mode
        }

        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.valves.LIGHTRAG_TIMEOUT
            )
            response.raise_for_status()
            return response.json()
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
                                yield f'data: {json.dumps({"choices": [{"delta": {"content": chunk}}]})}\n\n'
                            elif 'error' in data:
                                error_msg = data['error']
                                yield f'data: {json.dumps({"choices": [{"delta": {"content": f"错误: {error_msg}"}}]})}\n\n'
                        except json.JSONDecodeError:
                            continue

        except Exception as e:
            error_msg = f"LightRAG流式查询失败: {str(e)}"
            yield f'data: {json.dumps({"choices": [{"delta": {"content": error_msg}}]})}\n\n'

        yield "data: [DONE]\n\n"

    def pipe(
        self, user_message: str, model_id: str, messages: List[dict], body: dict,
        __event_emitter__=None, 
        __event_call__=None,
        __user__=None
    ) -> Union[str, Generator, Iterator]:
        f"""
        处理用户查询的主要方法 - {self.valves.PROFESSIONAL_DOMAIN}领域5阶段意图识别pipeline

        Args:
            user_message: 用户输入的消息
            model_id: 模型ID
            messages: 消息历史
            body: 请求体，包含流式设置和用户信息

        Returns:
            查询结果字符串或流式生成器
        """
        # 重置token统计
        self._reset_token_stats()

        # 验证必需参数
        if not self.valves.OPENAI_API_KEY:
            return "❌ 错误：缺少OpenAI API密钥，请在配置中设置OPENAI_API_KEY"

        if not user_message.strip():
            return "❌ 请提供有效的查询内容"

        # 打印调试信息
        if self.valves.DEBUG_MODE and "user" in body:
            print("=" * 50)
            print(f"用户: {body['user']['name']} ({body['user']['id']})")
            print(f"查询内容: {user_message}")
            print(f"流式响应: {body.get('stream', False)}")
            print(f"启用流式: {self.valves.ENABLE_STREAMING}")
            print("=" * 50)

        # 根据是否启用流式响应选择不同的处理方式
        if body.get("stream", False) and self.valves.ENABLE_STREAMING:
            return self._stream_response(user_message, messages)
        else:
            return self._non_stream_response(user_message, messages)

    def _stream_response(self, query: str, messages: List[dict]) -> Generator[str, None, None]:
        """流式响应处理 - 5阶段意图识别pipeline"""
        try:
            # 流式开始消息
            yield f'data: {json.dumps({"choices": [{"delta": {}, "finish_reason": None}]})}\n\n'

            # 第一阶段：意图识别
            intent_msg = {
                'choices': [{
                    'delta': {
                        'content': "**🧠 第一阶段：意图识别判断**\n正在分析问题意图..."
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(intent_msg)}\n\n"

            intent_result, can_direct_answer, need_knowledge_base = self._stage1_intent_recognition(query, messages)

            if can_direct_answer:
                # 直接回答，不需要搜索
                direct_answer_msg = {
                    'choices': [{
                        'delta': {
                            'content': f"\n✅ 意图识别：可直接回答\n\n**📝 直接回答：**\n{intent_result}"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(direct_answer_msg)}\n\n"

                # 添加token统计信息
                token_stats = self._get_token_stats()
                token_info_msg = {
                    'choices': [{
                        'delta': {
                            'content': f"\n\n---\n**Token消耗统计**\n- 输入Token: {token_stats['input_tokens']:,}\n- 输出Token: {token_stats['output_tokens']:,}\n- 总Token: {token_stats['total_tokens']:,}"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(token_info_msg)}\n\n"

                yield "data: [DONE]\n\n"
                return

            # 需要搜索或知识库处理
            intent_result_msg = {
                'choices': [{
                    'delta': {
                        'content': f"\n✅ 意图识别完成\n策略: {'需要知识库处理' if need_knowledge_base else '需要网络搜索'}\n原因: {intent_result}\n"
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(intent_result_msg)}\n\n"

            # 第二阶段：问题优化
            optimize_msg = {
                'choices': [{
                    'delta': {
                        'content': "\n**🔧 第二阶段：问题优化**\n正在优化查询问题..."
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(optimize_msg)}\n\n"

            optimized_query = self._stage2_optimize_query(query, messages)

            optimize_result_msg = {
                'choices': [{
                    'delta': {
                        'content': f"\n✅ 问题优化完成\n优化后查询: {optimized_query}\n"
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(optimize_result_msg)}\n\n"

            # 第三阶段：搜索
            search_msg = {
                'choices': [{
                    'delta': {
                        'content': "\n**🔍 第三阶段：SearxNG搜索**\n正在搜索相关信息..."
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(search_msg)}\n\n"

            search_results, search_status, search_links = self._stage3_search(optimized_query)

            search_result_msg = {
                'choices': [{
                    'delta': {
                        'content': f"\n{search_status}\n"
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(search_result_msg)}\n\n"

            if need_knowledge_base:
                # 需要知识库处理
                # 第四阶段：生成LightRAG查询
                lightrag_gen_msg = {
                    'choices': [{
                        'delta': {
                            'content': "\n**🧠 第四阶段：生成LightRAG查询**\n正在分析搜索结果并生成增强查询..."
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(lightrag_gen_msg)}\n\n"

                lightrag_query = self._stage4_generate_lightrag_query(query, search_results, messages)

                lightrag_gen_result_msg = {
                    'choices': [{
                        'delta': {
                            'content': f"\n✅ LightRAG查询生成完成\n增强查询: {lightrag_query[:100]}{'...' if len(lightrag_query) > 100 else ''}\n"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(lightrag_gen_result_msg)}\n\n"

                # 第五阶段：LightRAG问答
                lightrag_answer_msg = {
                    'choices': [{
                        'delta': {
                            'content': "\n**💭 第五阶段：LightRAG问答**\n"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(lightrag_answer_msg)}\n\n"

                # 流式生成LightRAG回答
                try:
                    for chunk_data in self._stage5_query_lightrag(lightrag_query, stream=True):
                        yield chunk_data
                except Exception as e:
                    error_msg = {
                        'choices': [{
                            'delta': {
                                'content': f"\n❌ LightRAG查询失败: {str(e)}"
                            },
                            'finish_reason': None
                        }]
                    }
                    yield f"data: {json.dumps(error_msg)}\n\n"
            else:
                # 只需要搜索结果回答
                search_answer_msg = {
                    'choices': [{
                        'delta': {
                            'content': f"\n**📝 基于搜索结果的回答：**\n\n{search_results}"
                        },
                        'finish_reason': None
                    }]
                }
                yield f"data: {json.dumps(search_answer_msg)}\n\n"

            # 添加token统计信息
            token_stats = self._get_token_stats()
            token_info_msg = {
                'choices': [{
                    'delta': {
                        'content': f"\n\n---\n**Token消耗统计**\n- 输入Token: {token_stats['input_tokens']:,}\n- 输出Token: {token_stats['output_tokens']:,}\n- 总Token: {token_stats['total_tokens']:,}"
                    },
                    'finish_reason': None
                }]
            }
            yield f"data: {json.dumps(token_info_msg)}\n\n"

        except Exception as e:
            error_msg = f"❌ Pipeline执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Stream error: {e}")
            yield f'data: {json.dumps({"choices": [{"delta": {"content": error_msg}}]})}\n\n'

        yield "data: [DONE]\n\n"

    def _non_stream_response(self, query: str, messages: List[dict]) -> str:
        """非流式响应处理 - 5阶段意图识别pipeline"""
        try:
            # 第一阶段：意图识别
            intent_result, can_direct_answer, need_knowledge_base = self._stage1_intent_recognition(query, messages)

            if can_direct_answer:
                # 直接回答，不需要搜索
                response_parts = []
                response_parts.append(f"**🧠 第一阶段：意图识别判断**\n策略: 可直接回答\n原因: {intent_result}")
                response_parts.append(f"\n**📝 直接回答：**\n{intent_result}")

                # 添加token统计信息
                token_stats = self._get_token_stats()
                token_info = f"\n\n---\n**Token消耗统计**\n- 输入Token: {token_stats['input_tokens']:,}\n- 输出Token: {token_stats['output_tokens']:,}\n- 总Token: {token_stats['total_tokens']:,}"

                return "\n".join(response_parts) + token_info

            # 第二阶段：问题优化
            optimized_query = self._stage2_optimize_query(query, messages)

            # 第三阶段：搜索
            search_results, search_status, search_links = self._stage3_search(optimized_query)

            response_parts = []
            response_parts.append(f"**🧠 第一阶段：意图识别判断**\n策略: {'需要知识库处理' if need_knowledge_base else '需要网络搜索'}\n原因: {intent_result}")
            response_parts.append(f"\n**🔧 第二阶段：问题优化**\n原始问题: {query}\n优化后查询: {optimized_query}")
            response_parts.append(f"\n**🔍 第三阶段：SearxNG搜索**\n{search_status}")

            if search_results and "搜索错误" not in search_results:
                # 显示搜索结果摘要
                lines = search_results.split('\n')
                summary_lines = []
                for line in lines[:8]:  # 只显示前8行
                    if line.strip():
                        summary_lines.append(line)
                if len(lines) > 8:
                    summary_lines.append("...")
                response_parts.append(f"\n搜索摘要:\n" + "\n".join(summary_lines))

            if need_knowledge_base:
                # 第四阶段：生成LightRAG查询
                lightrag_query = self._stage4_generate_lightrag_query(query, search_results, messages)

                # 第五阶段：LightRAG问答
                final_answer = self._stage5_query_lightrag(lightrag_query, stream=False)

                response_parts.append(f"\n**🧠 第四阶段：LightRAG查询生成**\n增强查询: {lightrag_query[:150]}{'...' if len(lightrag_query) > 150 else ''}")
                response_parts.append(f"\n**💭 第五阶段：LightRAG问答**\n{final_answer}")
            else:
                # 只基于搜索结果回答
                response_parts.append(f"\n**📝 基于搜索结果的回答：**\n\n{search_results}")

            # 添加token统计信息
            token_stats = self._get_token_stats()
            token_info = f"\n\n---\n**Token消耗统计**\n- 输入Token: {token_stats['input_tokens']:,}\n- 输出Token: {token_stats['output_tokens']:,}\n- 总Token: {token_stats['total_tokens']:,}"

            # 添加配置信息
            config_info = f"\n\n**配置信息**\n- 专业领域: {self.valves.PROFESSIONAL_DOMAIN}\n- 搜索结果数量: {self.valves.SEARXNG_SEARCH_COUNT}\n- LightRAG模式: {self.valves.LIGHTRAG_DEFAULT_MODE}\n- 意图识别置信度阈值: {self.valves.INTENT_CONFIDENCE_THRESHOLD}\n- 模型: {self.valves.OPENAI_MODEL}"

            return "\n".join(response_parts) + token_info + config_info

        except Exception as e:
            error_msg = f"❌ Pipeline执行失败: {str(e)}"
            if self.valves.DEBUG_MODE:
                print(f"Non-stream error: {e}")
            return error_msg
