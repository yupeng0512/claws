# CLAWS MCP 配置指南

> 所有 MCP 需在 Knot 平台 Web UI 中为对应 Agent 手动配置。

---

## 需要配置的 MCP 和 Agent 总览

| MCP 服务 | 连接方式 | 需配置的 Agent | 说明 |
|----------|---------|---------------|------|
| **github** | Streamable HTTP | Scout, Analyst, Reviewer | GitHub 项目搜索、代码读取、issue/commit 查询 |
| **fetch** | Streamable HTTP | Scout, Analyst | 访问任意 URL 并提取内容（补齐 web_search 无法访问 URL 的缺口） |

共需操作 **5 次**：为 3 个 Agent 配 GitHub + 为 2 个 Agent 配 Fetch。

---

## MCP 1: GitHub Remote MCP

GitHub 官方托管的远程 MCP 服务（2025-09 GA），无需自行部署。

### Knot 平台配置

| 表单字段 | 填写内容 |
|---------|---------|
| **名称** | `github` |
| **描述** | `GitHub 项目搜索、代码读取、issue/commit 查询` |
| **连接方式** | 选择 **Streamable HTTP** |

**服务配置** — 复制以下 JSON：

```json
{
  "mcpServers": {
    "github": {
      "url": "https://api.githubcopilot.com/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_GITHUB_PAT>"
      },
      "timeout": 60
    }
  }
}
```

> 将 `<YOUR_GITHUB_PAT>` 替换为你的 GitHub Personal Access Token。

### GitHub PAT 获取

1. 打开 https://github.com/settings/tokens
2. Generate new token (classic)
3. 勾选权限：
   - `public_repo` — 读取公开仓库（必需）
   - `read:org` — 读取组织信息（可选）
4. 复制生成的 `ghp_xxxx` token

### 需要为以下 Agent 配置

| Agent | 使用的 GitHub 工具 |
|-------|-------------------|
| **Scout** | `search_repositories`, `list_commits` — 发现项目、跟踪 releases |
| **Analyst** | `get_file_contents`, `list_issues`, `search_code` — 分析代码和活跃度 |
| **Reviewer** | `search_repositories`, `list_issues` — 验证结论、检查真实性 |

---

## MCP 2: Fetch MCP（自托管，URL 内容提取）

基于 `mcp-fetch-streamablehttp-server` 自托管在 work 机器上的 Fetch 服务。
完全免费、无限制、无需第三方 API Key。

### 为什么需要这个？

测试验证发现 web_search 的本质是搜索引擎查询，Agent 无法"打开一个指定 URL 并读取其内容"。
Fetch MCP 补齐了这个缺口：给定 URL → 返回结构化内容。

### 服务状态

已部署为 Docker 容器，随 CLAWS 一起自动启动：

| 项目 | 值 |
|------|-----|
| 容器名 | `fetch-mcp` |
| 对内地址 | `http://fetch-mcp.dev.local/mcp`（Traefik 域名路由） |
| **Knot 地址** | **`http://<YOUR_MACHINE_IP>/fetch-mcp/mcp`**（Traefik PathPrefix 路由，80 端口） |
| Docker Compose | `/data/workspace/claws/docker-compose.yml` |

### Knot 平台配置

| 表单字段 | 填写内容 |
|---------|---------|
| **名称** | `fetch` |
| **描述** | `访问指定 URL 并提取内容（Markdown），支持网页、GitHub 文件等` |
| **连接方式** | 选择 **Streamable HTTP** |

**服务配置** — 复制以下 JSON：

```json
{
  "mcpServers": {
    "fetch": {
      "security_zone": "devnet",
      "url": "http://<YOUR_MACHINE_IP>/fetch-mcp/mcp",
      "timeout": 60
    }
  }
}
```

> 无需 API Key，无需 Headers——服务跑在自己的机器上。
> `security_zone: "devnet"` 告诉 Knot 这是 DevCloud 内网部署的 MCP，通过 80 端口访问。

### 需要为以下 Agent 配置

| Agent | 用途 |
|-------|------|
| **Scout** | 抓取 GitHub README、技术博客、项目页面的原始内容 |
| **Analyst** | 读取 GitHub 源码文件（raw URL）、issue 详情页、技术文档 |

---

## 完整配置清单 (Checklist)

按顺序执行，打钩确认：

```
□ 1. 获取 GitHub PAT (ghp_xxxx)
□ 2. 确认 fetch-mcp 容器运行中 (docker ps | grep fetch-mcp)

□ 3. Scout Agent    → 添加 github MCP (Streamable HTTP)
□ 4. Scout Agent    → 添加 fetch MCP  (Streamable HTTP)
□ 5. Analyst Agent  → 添加 github MCP (Streamable HTTP)
□ 6. Analyst Agent  → 添加 fetch MCP  (Streamable HTTP)
□ 7. Reviewer Agent → 添加 github MCP (Streamable HTTP)

□ 8. 验证：手动触发 SENSE 阶段，检查日志
```

---

## 验证

配置完成后通过 Admin Dashboard 手动触发验证：

```
http://claws.dev.local/ → 调度管理 → 手动触发 → 侦察 + 筛选
```

或通过 API：

```bash
curl -X POST http://claws.dev.local/api/trigger/sense
```

### 手动验证 Fetch MCP

```bash
curl -s -X POST http://<YOUR_MACHINE_IP>/fetch-mcp/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"fetch","arguments":{"url":"https://example.com","max_length":500}},"id":1}'
```

---

## 运维

### 重启 Fetch MCP

```bash
cd /data/workspace/claws && docker compose restart fetch-mcp
```

### 查看日志

```bash
docker logs fetch-mcp --tail 20
```

### 服务异常排查

1. 确认容器运行: `docker ps | grep fetch-mcp`
2. 确认路由: `curl http://<YOUR_MACHINE_IP>/fetch-mcp/mcp -X POST -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}},"id":1}'`
3. 如果无响应，检查是否在安装依赖（首次启动需约 30 秒 pip install）

---

## 附录：本地 Cursor 配置模板

以下配置用于本地 Cursor IDE 的 `mcp.json`，非 Knot 平台使用。

### GitHub MCP (Stdio)

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "<YOUR_GITHUB_PAT>"
      },
      "disabled": false
    }
  }
}
```

### Fetch MCP (Stdio, Anthropic 官方)

```json
{
  "mcpServers": {
    "fetch": {
      "command": "uvx",
      "args": ["mcp-server-fetch"],
      "disabled": false
    }
  }
}
```

---

## 方案选型说明

### 为什么自托管而非第三方远程服务？

| 方案 | 免费额度 | Knot 兼容 | 可靠性 |
|------|---------|----------|--------|
| Jina AI MCP | ❌ 额度已耗尽 (0) | ✅ | 受限于第三方 |
| Firecrawl | ❌ 500 credits 一次性 | ✅ | 额度不足 |
| mcp-server-fetch (stdio) | ✅ 无限 | ❌ Knot 无法运行 | — |
| **自托管 fetch (HTTP)** | **✅ 无限** | **✅ IP 直连** | **完全自控** |

自托管方案跑在自己机器上，无额度限制、无第三方依赖、Knot 通过 IP 直连。

### 能力闭环

```
web_search  → 搜索引擎发现项目（关键词 → 搜索结果）
fetch MCP   → 访问指定 URL 读取内容（URL → Markdown）
github MCP  → GitHub API 结构化查询（参数 → 精确数据）
```

三者互补，形成完整的信息获取能力。
