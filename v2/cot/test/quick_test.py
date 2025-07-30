#!/usr/bin/env python3
"""
LightRAG流式接口快速测试脚本
用于快速测试单个查询的流式输出
"""

import requests
import json
import time
import sys
from datetime import datetime


def quick_test_stream(base_url="http://117.50.252.245:9621", query="什么是人工智能？", mode="hybrid"):
    """快速测试流式查询功能"""
    stream_url = f"{base_url}/query/stream"
    
    print(f"🚀 快速测试LightRAG流式接口")
    print(f"🌐 服务地址: {base_url}")
    print(f"📝 查询内容: {query}")  
    print(f"🔧 查询模式: {mode}")
    print(f"📡 请求URL: {stream_url}")
    print("=" * 60)
    
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
        print("📤 发送请求...")
        response = requests.post(
            stream_url,
            json=payload,
            headers=headers,
            timeout=30,
            stream=True
        )
        
        print(f"📡 HTTP状态码: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ 请求失败: {response.text}")
            return False
        
        print("\n📨 接收流式数据:")
        print("-" * 40)
        
        buffer = ""
        total_content = ""
        chunk_count = 0
        
        # 处理流式响应
        for chunk in response.iter_content(chunk_size=512):
            if chunk:
                # 确保chunk是字符串类型
                if isinstance(chunk, bytes):
                    chunk = chunk.decode('utf-8', errors='ignore')
                buffer += chunk
                chunk_count += 1
                
                # 按行处理NDJSON
                while '\n' in buffer:
                    line, buffer = buffer.split('\n', 1)
                    line = line.strip()
                    
                    if line:
                        try:
                            json_data = json.loads(line)
                            
                            timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                            
                            if "error" in json_data:
                                print(f"[{timestamp}] ❌ 错误: {json_data['error']}")
                                return False
                            
                            if "response" in json_data:
                                response_content = json_data["response"]
                                total_content += response_content
                                print(f"[{timestamp}] 📝 {response_content}", end='', flush=True)
                                
                        except json.JSONDecodeError as e:
                            print(f"\n⚠️ JSON解析失败: {e}")
                            continue
        
        # 处理最后的缓冲区
        if buffer.strip():
            try:
                json_data = json.loads(buffer.strip())
                if "response" in json_data:
                    response_content = json_data["response"]
                    total_content += response_content
                    print(response_content, end='', flush=True)
                elif "error" in json_data:
                    print(f"\n❌ 最终错误: {json_data['error']}")
            except json.JSONDecodeError:
                pass
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"\n\n" + "=" * 60)
        print(f"✅ 流式查询完成!")
        print(f"📊 统计信息:")
        print(f"   - 耗时: {duration:.2f} 秒")
        print(f"   - 总内容长度: {len(total_content)} 字符")
        print(f"   - 数据块数量: {chunk_count}")
        
        return True
        
    except requests.exceptions.Timeout:
        print("❌ 请求超时")
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ 请求异常: {e}")
        return False
    except Exception as e:
        print(f"❌ 未知错误: {e}")
        return False


def main():
    """主函数"""
    # 默认参数
    base_url = "http://117.50.252.245:9621"
    query = "什么是人工智能？"
    mode = "hybrid"
    
    # 解析命令行参数
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    if len(sys.argv) > 2:
        query = sys.argv[2]
    if len(sys.argv) > 3:
        mode = sys.argv[3]
    
    print("💡 使用方法: python quick_test.py [服务地址] [查询内容] [模式]")
    print(f"   例如: python quick_test.py http://117.50.252.245:9621 '什么是机器学习？' hybrid")
    print()
    
    # 运行测试
    success = quick_test_stream(base_url, query, mode)
    
    if success:
        print("🎉 测试成功！")
    else:
        print("❌ 测试失败！")
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main() 