#!/usr/bin/env python3
"""
LightRAG流式接口测试脚本
测试 http://117.50.252.245:9621/query/stream 接口的流式输出功能
"""

import requests
import json
import time
import sys
from datetime import datetime


class LightRAGStreamTester:
    def __init__(self, base_url="http://117.50.252.245:9621"):
        self.base_url = base_url
        self.stream_url = f"{base_url}/query/stream"
        self.health_url = f"{base_url}/health"
        
    def test_health(self):
        """测试服务健康状态"""
        print("🔍 测试服务健康状态...")
        try:
            response = requests.get(self.health_url, timeout=10)
            if response.status_code == 200:
                print("✅ LightRAG服务运行正常")
                return True
            else:
                print(f"⚠️ 服务响应异常，状态码: {response.status_code}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"❌ 无法连接到服务: {e}")
            return False
    
    def test_stream_query(self, query, mode="hybrid", timeout=30):
        """测试流式查询功能"""
        print(f"\n🚀 开始测试流式查询")
        print(f"查询内容: {query}")
        print(f"查询模式: {mode}")
        print(f"目标URL: {self.stream_url}")
        print("-" * 60)
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive"
        }
        
        payload = {
            "query": query,
            "mode": mode
        }
        
        start_time = time.time()
        
        try:
            response = requests.post(
                self.stream_url,
                json=payload,
                headers=headers,
                timeout=timeout,
                stream=True
            )
            
            print(f"📡 HTTP状态码: {response.status_code}")
            print(f"📋 响应头: {dict(response.headers)}")
            
            if response.status_code != 200:
                print(f"❌ 请求失败: {response.text}")
                return False
            
            print("\n📨 开始接收流式数据:")
            print("=" * 60)
            
            buffer = ""
            total_content = ""
            chunk_count = 0
            
            # 处理流式响应
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    # 确保chunk是字符串类型
                    if isinstance(chunk, bytes):
                        chunk = chunk.decode('utf-8', errors='ignore')
                    buffer += chunk
                    chunk_count += 1
                    
                    # 按行处理NDJSON数据
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.strip()
                        
                        if line:
                            try:
                                json_data = json.loads(line)
                                
                                # 打印时间戳
                                timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                                print(f"[{timestamp}] 📦 接收到数据块 #{chunk_count}")
                                
                                # 检查错误
                                if "error" in json_data:
                                    print(f"❌ 错误: {json_data['error']}")
                                    return False
                                
                                # 处理正常响应
                                if "response" in json_data:
                                    response_content = json_data["response"]
                                    total_content += response_content
                                    print(f"📝 内容: {response_content}")
                                    
                                # 打印完整的JSON数据（用于调试）
                                print(f"🔍 原始JSON: {json.dumps(json_data, ensure_ascii=False)}")
                                print("-" * 40)
                                
                            except json.JSONDecodeError as e:
                                print(f"⚠️ JSON解析错误: {line} - {str(e)}")
                                continue
            
            # 处理最后的缓冲区内容
            if buffer.strip():
                try:
                    json_data = json.loads(buffer.strip())
                    if "response" in json_data:
                        response_content = json_data["response"]
                        total_content += response_content
                        print(f"📝 最终内容: {response_content}")
                    elif "error" in json_data:
                        print(f"❌ 最终错误: {json_data['error']}")
                except json.JSONDecodeError:
                    print(f"⚠️ 无法解析最后的响应片段: {buffer}")
            
            end_time = time.time()
            duration = end_time - start_time
            
            print("=" * 60)
            print(f"✅ 流式查询完成!")
            print(f"📊 统计信息:")
            print(f"   - 耗时: {duration:.2f} 秒")
            print(f"   - 数据块数量: {chunk_count}")
            print(f"   - 总内容长度: {len(total_content)} 字符")
            print(f"   - 总内容预览: {total_content[:200]}{'...' if len(total_content) > 200 else ''}")
            
            return True
            
        except requests.exceptions.Timeout:
            print(f"❌ 请求超时 ({timeout}秒)")
            return False
        except requests.exceptions.RequestException as e:
            print(f"❌ 请求异常: {e}")
            return False
        except Exception as e:
            print(f"❌ 未知错误: {e}")
            return False
    
    def run_tests(self):
        """运行所有测试"""
        print("🧪 LightRAG流式接口测试开始")
        print(f"🌐 目标服务: {self.base_url}")
        print(f"⏰ 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)
        
        # 测试1: 服务健康检查
        if not self.test_health():
            print("❌ 服务不可用，测试终止")
            return False
        
        # 测试2: 基础流式查询测试
        test_queries = [
            {
                "query": "什么是人工智能？",
                "mode": "hybrid",
                "description": "基础中文查询测试"
            },
            {
                "query": "What is machine learning?",
                "mode": "hybrid", 
                "description": "基础英文查询测试"
            },
            {
                "query": "深度学习的发展历程",
                "mode": "local",
                "description": "本地模式查询测试"
            },
            {
                "query": "Python编程语言特点",
                "mode": "global",
                "description": "全局模式查询测试"
            }
        ]
        
        success_count = 0
        total_tests = len(test_queries)
        
        for i, test_case in enumerate(test_queries, 1):
            print(f"\n🧪 测试 {i}/{total_tests}: {test_case['description']}")
            if self.test_stream_query(
                query=test_case["query"],
                mode=test_case["mode"],
                timeout=30
            ):
                success_count += 1
                print(f"✅ 测试 {i} 通过")
            else:
                print(f"❌ 测试 {i} 失败")
            
            # 测试间隔
            if i < total_tests:
                print("⏳ 等待2秒后继续下一个测试...")
                time.sleep(2)
        
        # 测试总结
        print("\n" + "=" * 80)
        print("📊 测试总结:")
        print(f"   - 总测试数: {total_tests}")
        print(f"   - 成功数: {success_count}")
        print(f"   - 失败数: {total_tests - success_count}")
        print(f"   - 成功率: {success_count/total_tests*100:.1f}%")
        
        if success_count == total_tests:
            print("🎉 所有测试通过！LightRAG流式接口工作正常")
            return True
        else:
            print("⚠️ 部分测试失败，请检查服务状态")
            return False


def main():
    """主函数"""
    # 检查命令行参数
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    else:
        base_url = "http://117.50.252.245:9621"
    
    print(f"🚀 使用服务地址: {base_url}")
    
    # 创建测试器并运行测试
    tester = LightRAGStreamTester(base_url)
    success = tester.run_tests()
    
    # 退出码
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main() 