# PubChemPy FastMCP Server

一个基于 FastMCP 框架的化学物质搜索服务器，使用 PubChemPy 库访问 PubChem 数据库。

## 功能特性

- 🚀 **FastMCP 框架**: 使用现代化的 FastMCP 2.0 框架，代码简洁高效
- 🧪 **多种搜索方式**: 支持化学名称、分子式、SMILES 字符串搜索
- 🔄 **容错机制**: PubChemPy 失败时自动切换到直接 API 调用
- ⚡ **异步并发**: 使用 asyncio 提升性能
- 🔌 **MCP 协议**: 符合 Model Context Protocol 标准，LLM 可直接调用
- 🌐 **HTTP传输**: 专注于HTTP API，简化部署和集成
- 🐳 **Docker 支持**: 完整的 Docker 部署方案
- 📊 **详细信息**: 返回完整的分子式信息
- 📝 **Context 日志**: 支持向客户端发送执行日志

## 项目结构

```
pubchempy_mcp/
├── src/
│   ├── __init__.py
│   └── mcp_server.py          # FastMCP 服务器主文件
├── requirements.txt           # Python 依赖（简化版）
├── Dockerfile                # Docker 镜像构建（简化版）
├── docker-compose.yml        # Docker Compose 配置
├── start.sh                  # 服务器启动脚本
└── README.md                 # 项目文档
```

## 快速开始

### 方法 1: 使用启动脚本 (推荐)

```bash
# 启动FastMCP服务器
chmod +x start.sh
./start.sh
```

### 方法 2: 手动安装

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 启动FastMCP服务器
python src/mcp_server.py
```

### 方法 3: 使用 Docker

```bash
# 构建并运行
docker-compose up --build

# 后台运行
docker-compose up -d --build
```

### 方法 4: 使用 FastMCP CLI (如果安装了 FastMCP)

```bash
# 使用 HTTP 传输运行
fastmcp run src/mcp_server.py --transport http --port 8989
```

## 使用说明

### 工具功能

#### search_chemical

搜索化学物质信息，支持多种搜索类型，现在包含 Context 日志支持：

**参数:**
- `query` (必需): 搜索查询字符串
- `search_type` (可选): 搜索类型，默认为 "formula"
  - `"name"`: 按化学名称搜索
  - `"formula"`: 按分子式搜索  
  - `"smiles"`: 按SMILES字符串搜索
- `use_fallback` (可选): 是否使用备用API，默认为 false

### 资源端点

#### health://status
获取服务器健康状态

#### server://info
获取服务器详细信息

**示例:**

```bash
# 通过分子式搜索水分子
search_chemical(query="H2O", search_type="formula")

# 通过名称搜索咖啡因
search_chemical(query="caffeine", search_type="name")

# 通过SMILES搜索
search_chemical(query="CCO", search_type="smiles")
```

**返回信息:**
- PubChem CID
- IUPAC 名称
- 分子式
- 分子量
- SMILES 表示
- InChI 和 InChI Key
- 化学物质别名
- 分子属性（原子数、键数、极性表面积等）

## 技术架构

### FastMCP 框架优势

- **简化开发**: 使用装饰器方式定义工具和资源，代码更简洁
- **自动类型推断**: 基于函数签名自动生成MCP工具模式
- **Context 支持**: 内置日志和进度报告功能
- **HTTP API**: 专注于HTTP传输，提供RESTful接口
- **错误处理**: 简化的异常处理机制

### 数据源

1. **PubChemPy**: Python 包装器，简化API调用
2. **PubChem REST API**: 直接API调用，作为备用方案

### 传输协议

- **HTTP**: Web API模式，支持RESTful调用和Docker部署，便于与各种客户端集成

## 配置选项

### 运行方式

FastMCP 服务器使用 HTTP 传输，通过环境变量配置端口：

```python
# 服务器启动代码
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8989"))
    mcp.run(transport="http", host="0.0.0.0", port=port)
```

### 环境变量

- `PORT`: HTTP服务器端口号（默认: 8989）

## 依赖项

- Python 3.11+
- fastmcp >= 2.0.0
- pubchempy >= 1.0.4
- httpx >= 0.25.0
- pydantic >= 2.4.0

## 与 LLM 集成

### Claude Desktop

将以下配置添加到 Claude Desktop 的 MCP 设置中：

```json
{
  "pubchempy": {
    "command": "python",
    "args": ["src/mcp_server.py"],
    "cwd": "/path/to/pubchempy_mcp"
  }
}
```

### 其他 MCP 客户端

本服务器符合标准 MCP 协议，可以与任何支持 MCP 的客户端集成。

## 开发指南

### 代码风格

- 使用 FastMCP 装饰器定义工具和资源
- 利用 Context 参数提供日志和进度信息
- 保持函数简洁，单一职责
- 使用类型注解

### 测试

```bash
# 安装开发依赖
pip install -r requirements.txt

# 运行测试
python -m pytest tests/
```

## FastMCP vs 传统 MCP

### 代码简化对比

**传统 MCP:**
```python
@server.list_tools()
async def handle_list_tools() -> ListToolsResult:
    return ListToolsResult(tools=[...])

@server.call_tool()  
async def handle_call_tool(request: CallToolRequest) -> CallToolResult:
    # 复杂的参数解析和响应构建
    ...
```

**FastMCP:**
```python
@mcp.tool()
async def search_chemical(query: str, search_type: str = "formula") -> str:
    # 直接返回结果，框架自动处理协议细节
    ...
```

### 主要改进

1. **代码量减少 70%**: 从 546 行减少到约 380 行
2. **更好的类型安全**: 基于函数签名的自动类型推断
3. **简化的错误处理**: 内置异常处理机制
4. **内置日志支持**: Context 对象提供日志功能
5. **多传输协议**: 自动支持多种传输方式

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 相关链接

- [FastMCP 官方文档](https://gofastmcp.com/)
- [PubChemPy 文档](https://pubchempy.readthedocs.io/)
- [PubChem 数据库](https://pubchem.ncbi.nlm.nih.gov/)
- [Model Context Protocol](https://modelcontextprotocol.io/)