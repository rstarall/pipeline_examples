# PubChemPy MCP Server

一个基于 Model Context Protocol (MCP) 的化学物质搜索服务器，使用 PubChemPy 库访问 PubChem 数据库。

## 功能特性

- 🧪 **多种搜索方式**: 支持化学名称、分子式、SMILES 字符串搜索
- 🔄 **容错机制**: PubChemPy 失败时自动切换到直接 API 调用
- ⚡ **异步并发**: 使用 asyncio 提升性能
- 🔌 **MCP 协议**: 符合 Model Context Protocol 标准，LLM 可直接调用
- 🐳 **Docker 支持**: 完整的 Docker 部署方案
- 📊 **详细信息**: 返回完整的分子式信息

## 项目结构

```
pubchempy_mcp/
├── src/
│   ├── __init__.py
│   └── mcp_server.py          # MCP 服务器主文件
├── requirements.txt           # Python 依赖
├── Dockerfile                # Docker 镜像构建
├── docker-compose.yml        # Docker Compose 配置
├── start.sh                  # 服务器启动脚本
├── config.py                 # 配置文件
├── .env.example              # 环境变量示例
└── README.md                 # 项目文档
```

## 快速开始

### 方法 1: 使用启动脚本 (推荐)

```bash
# 启动MCP服务器
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

# 启动MCP服务器
python -m src.mcp_server
```

### 方法 3: Docker 部署

```bash
# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f mcp-server

# 停止服务
docker-compose down
```

## MCP 工具

### search_chemical

搜索化学物质的 MCP 工具。

**参数:**
- `query` (必需): 化学名称、分子式或 SMILES 字符串
- `search_type` (可选): 搜索类型 - `name`, `formula`, `smiles`，默认 `formula`
- `use_fallback` (可选): 使用直接 API 备用选项，默认 `false`

**示例工具调用:**
```json
{
  "name": "search_chemical",
  "arguments": {
    "query": "caffeine",
    "search_type": "name"
  }
}
```

**返回结果:**
```
🧪 Chemical Search Results
Query: caffeine
Search Type: name
Source: pubchempy
Found 1 compound(s)

--- Compound 1 ---
PubChem CID: 2519
IUPAC Name: 1,3,7-trimethylpurine-2,6-dione
Molecular Formula: C8H10N4O2
Molecular Weight: 194.19 g/mol
SMILES: CN1C=NC2=C1C(=O)N(C(=O)N2C)C
InChI Key: RYYVLZVUVIJVGH-UHFFFAOYSA-N
Synonyms: caffeine, 1,3,7-Trimethylxanthine, Theine

Properties:
  Heavy Atom Count: 14
  H Bond Donor Count: 0
  H Bond Acceptor Count: 6
  ...
```

## LLM 集成

### Claude Desktop 配置

在 `claude_desktop_config.json` 中添加:

```json
{
  "mcpServers": {
    "pubchempy": {
      "command": "python",
      "args": ["-m", "src.mcp_server"],
      "cwd": "/path/to/pubchempy_mcp"
    }
  }
}
```

### 其他 MCP 客户端

任何支持 MCP 协议的客户端都可以连接到这个服务器:

```bash
# 直接通过stdio运行
python -m src.mcp_server
```

## 使用示例

### 搜索化学物质

```
用户: 搜索咖啡因的化学信息
LLM: 我来为你搜索咖啡因的化学信息。

[调用 search_chemical 工具]
{
  "query": "caffeine", 
  "search_type": "name"
}

结果显示咖啡因的分子式是 C8H10N4O2，分子量为 194.19 g/mol...
```

### 通过分子式搜索

```
用户: H2O 是什么化合物？
LLM: [调用 search_chemical 工具]
{
  "query": "H2O",
  "search_type": "formula"  
}

这是水分子，分子量为 18.02 g/mol...
```

## 环境变量

- `LOG_LEVEL`: 日志级别 (debug, info, warning, error)，默认 `info`
- `PYTHONPATH`: Python 路径

## 容错机制

服务器提供两层容错机制：

1. **PubChemPy 优先**: 默认使用 PubChemPy 库
2. **API 备用**: PubChemPy 失败时自动切换到直接 API 调用
3. **手动指定**: 可通过 `use_fallback=true` 直接使用备用 API

## 开发

### 本地开发

```bash
# 激活虚拟环境
source venv/bin/activate

# 运行服务器
python -m src.mcp_server
```

### 调试

MCP 服务器使用 stdio 进行通信，可以通过日志进行调试：

```bash
# 查看日志
tail -f logs/server.log

# Docker 日志
docker-compose logs -f mcp-server
```

## 故障排除

### 常见问题

1. **PubChemPy 连接失败**
   - 检查网络连接
   - 使用 `use_fallback=true` 启用备用 API

2. **MCP 连接问题**
   - 确保 LLM 客户端支持 MCP 协议
   - 检查服务器日志输出

3. **依赖安装失败**
   - 更新 pip：`pip install --upgrade pip`
   - 使用国内镜像：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt`

## 协议说明

这个服务器实现了 Model Context Protocol (MCP) 规范:

- **传输层**: stdio (标准输入输出)
- **通信格式**: JSON-RPC 2.0
- **工具**: `search_chemical`
- **资源**: 无
- **提示**: 无

## 许可证

MIT License

## 贡献

欢迎提交 Issue 和 Pull Request！

## 参考资料

- [Model Context Protocol](https://github.com/modelcontextprotocol)
- [PubChemPy 文档](https://pubchempy.readthedocs.io/)
- [PubChem REST API](https://pubchempy.readthedocs.io/en/latest/guide/searching.html) 