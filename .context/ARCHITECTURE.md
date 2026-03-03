# CLAWS 架构概览

## 定位

CLAWS (Continuous Learning And Working System) 是一个 7x24 小时自主运行的技术趋势发现引擎。它不是被动等待指令的助手，而是一个有独立品味、能自我进化的自主探索者。

## 核心循环

```
SENSE --> FILTER --> DIVE --> DISTILL --> REFLECT
(感知)    (筛选)    (深挖)    (提炼)     (反思)
  |                                        |
  |       品味模型 (TASTE.md)               |
  |          ^          |                  |
  |          |          v                  |
  |       反馈更新 <-- 评估结果 ────────────┘
  └────────────────────────────────────────┘
```

## 技术栈

- **运行时**: Python 3.11, Docker
- **调度**: APScheduler (AsyncIOScheduler)
- **AI 平台**: Knot Agent (AG-UI 协议, 流式 SSE)
- **推送**: 飞书 Webhook (Flow, 纯文本格式)
- **监控**: Ops Dashboard (ops_reporter.py)
- **存储**: 本地 Markdown 文件 (memory/) + SQLite FTS5 索引
- **状态管理**: Pipeline State Machine (JSON 持久化)

## Knot Agent 平台能力

Knot Agent 平台已具备以下能力（v3 修正认知）：

| 能力 | 状态 | 说明 |
|------|------|------|
| Shell 命令执行 | 内置 Client 工具 | Agent 可直接运行命令 |
| 浏览器自动化 | 内置 Client 工具 | Agent 可操作浏览器 |
| 文件读写/搜索 | 内置 Client 工具 | 通过云工作区 |
| MCP 服务 | 平台支持 | 需人工在 Web UI 配置 |
| Skills | 平台支持 | 需人工在 Web UI 配置 |
| 子智能体 | 平台支持 | 需人工在 Web UI 配置 |
| 知识库 | 平台支持 | 需人工在 Web UI 配置 |
| Rules | 平台支持 | 需人工在 Web UI 编辑 |

瓶颈：MCP/Skills/子智能体等扩展能力无法在对话中由 Agent 实时自主安装，需人工操作。

## Runner 层角色定义

Runner 不重造 Knot Agent 已有能力，专注于：

- **Pipeline 编排**: 4 Phase 调度 + 断点恢复 + 失败重试
- **状态管理**: Pipeline State Machine (memory/state/)
- **会话持久化**: conversation_id 复用实现跨轮上下文
- **推送格式化**: 5 种场景统一纯文本模板
- **记忆索引**: SQLite FTS5 全文检索 + 时间衰减
- **预注入上下文**: 在构建 prompt 时附带运行统计、记忆检索结果
- **自进化**: 收集运行统计注入 Evolve prompt，驱动参数自调

## 四 Agent Pipeline 架构

```
本地调度器 (APScheduler) + Pipeline State Machine
     |
     +-- Phase 1: Scout (侦察兵)
     |   +-- 模型: deepseek-v3.2 + web search
     |   +-- 职责: 扫描 GitHub Trending / TrendRadar / HN / Twitter
     |   +-- 输出: JSON (items[] + scores + verdict)
     |
     +-- Phase 2: Analyst (分析师)
     |   +-- 模型: claude-4.5-sonnet + web search
     |   +-- 职责: 对 deep_dive 项做深度研究 + 商业评估
     |   +-- 输出: Markdown 分析报告 + JSON metadata
     |   +-- 预注入: 相关历史记忆 (FTS5 检索)
     |
     +-- Phase 3: Evolve (进化者)
     |   +-- 模型: claude-4.5-sonnet (无 web)
     |   +-- 职责: 反思探索质量，改写 TASTE.md / SOUL.md
     |   +-- 输出: JSON (taste_evolution + new_discoveries + reflection)
     |   +-- 预注入: 运行统计
     |
     +-- Phase 4: Reviewer (审查者)
         +-- 模型: claude-4.5-sonnet + web search
         +-- 职责: 独立审计，替代人工反馈回路
         +-- 输出: JSON (overall_grade + feedback_signals)
```

每个 Agent 拥有独立的 Knot Agent ID，共用同一个云工作区。
会话通过 conversation_id 跨轮持久化，每周日自动重置。

## 调度节奏

| 阶段 | 频率 | Agent | 触发方式 |
|------|------|-------|---------|
| SENSE + FILTER | 每 4h | Scout | IntervalTrigger |
| DIVE | 10:00 / 22:00 | Analyst | CronTrigger |
| REFLECT + EVOLVE | 21:00 | Evolve | CronTrigger |
| REVIEW | 21:30 | Reviewer | CronTrigger |
| WEEKLY | 周日 15:00 | Evolve | CronTrigger |

首次启动时立即执行一次 SENSE+FILTER。

## Pipeline 状态机

- 每日执行状态持久化到 memory/state/<date>.json
- Phase 状态: pending -> running -> success/failed/skipped
- 依赖检查: DIVE 依赖 SENSE, REVIEW 依赖 REFLECT
- 失败自动重试: 最多 3 次
- 数据回退: DIVE 若今日无 SENSE 数据，自动回退到最近成功日期的数据

## 自进化机制

### 品味渐变 (Taste Drift)
- Evolve Agent 输出 `taste_evolution.new_taste_md` -> Runner 覆盖写入 `TASTE.md`
- 变更记录追加到 `memory/taste-changelog.md`
- Reviewer 的 `feedback_signals` 在下轮进化时被 Evolve 参考

### 系统级自省 (v3 新增)
- 每周收集各 Phase 成功率、平均耗时、重试次数
- 注入到 WEEKLY Evolve prompt 的系统统计区域
- Evolve Agent 根据统计数据建议参数调整

### 写入职责分离
- **Runner** 是唯一文件写入者 (TASTE.md / SOUL.md / DISCOVERIES.md / 所有 memory/)
- **Agent** 只输出 JSON 结构，不直接写文件

## 记忆系统

- **存储**: 本地 Markdown 文件 (memory/)
- **索引**: SQLite FTS5 全文检索 (memory/.memory_index.db)
- **时间衰减**: 越新的文件权重越高
- **增量更新**: 只索引变更文件
- **上下文注入**: 检索结果自动注入到 Agent prompt

## 部署

```
Docker 容器 (claws)
+-- 网络: traefik-net (Traefik 反向代理) + ops-net (内部通信)
+-- 域名: claws.dev.local (通过 Traefik 路由)
+-- 卷挂载:
|   +-- ./memory -> /app/memory (探索记忆 + 状态 + 会话 + 索引)
|   +-- ./logs -> /app/logs (日志轮转)
|   +-- ./TASTE.md / SOUL.md / CLAWS.md -> /app/ (品味模型)
|   +-- ./config -> /app/config:ro (Agent 配置 + Prompt)
|   +-- ./dashboard -> /app/dashboard:ro (Admin Dashboard 前端)
+-- 入口: python -u claws_runner.py
+-- 健康检查: 120s 间隔, 检查 claws.log 存在且非空
+-- 日志: json-file, 10MB x 3 轮转
```

访问方式：`http://claws.dev.local/` (通过 Traefik 反向代理，无直接端口暴露)。
配置挂载策略：Dockerfile 中 `COPY config/` 提供镜像内置默认值，`docker-compose.yml` 的 volume mount 在运行时覆盖。修改 Prompt 或调度配置后只需 `docker compose restart claws`，无需重建镜像。

## 与其他系统的集成

| 系统 | 角色 | 通信方式 |
|------|------|---------|
| Knot Agent 平台 | AI 推理 + 工具执行 | HTTP POST -> SSE 流式 |
| ops-dashboard | 运维监控 | ops_reporter.py -> HTTP POST /api/events |
| 飞书 | 推送 | Flow Webhook POST (纯文本) |
| GitHub Trending | 信号源 | 通过 Agent 的 web search / 未来通过 MCP |

## 文件结构

```
claws/
+-- claws_runner.py          # 主引擎 (Pipeline + 调度 + 推送模板 + 会话管理 + 预注入)
+-- pipeline_state.py        # Pipeline 状态机 (断点恢复 + 重试)
+-- memory_store.py          # SQLite FTS5 记忆检索
+-- ops_reporter.py          # Ops Dashboard 上报 SDK
+-- docker-compose.yml       # Docker 部署
+-- Dockerfile
+-- .env                     # 密钥和配置 (Agent ID / Token)
+-- .env.example             # 配置模板
+-- CLAWS.md                 # 探索协议文档
+-- TASTE.md                 # 品味模型 (自进化)
+-- SOUL.md                  # 探索者灵魂 (自进化)
+-- config/
|   +-- agents.yaml          # Agent 角色定义 + 调度配置 + MCP 推荐
|   +-- agents/
|       +-- scout/main.md    # Scout Prompt
|       +-- analyst/main.md  # Analyst Prompt
|       +-- evolve/main.md   # Evolve Prompt
|       +-- reviewer/main.md # Reviewer Prompt
+-- memory/
|   +-- raw/                 # Phase 1 原始采集
|   +-- filtered/            # Phase 2 筛选结果
|   +-- deep-dives/          # Phase 3 深度分析
|   +-- reflections/         # 反思
|   +-- reviews/             # 审查报告
|   +-- feedback/            # Reviewer 反馈信号 (JSON)
|   +-- state/               # Pipeline 每日状态 (JSON)
|   +-- sessions.json        # 会话持久化 (conversation_id)
|   +-- .memory_index.db     # SQLite FTS5 索引
|   +-- DISCOVERIES.md       # 累积发现库
|   +-- taste-changelog.md   # 品味进化历史
+-- logs/
|   +-- claws.log            # 运行日志 (10MB x 5 轮转)
|   +-- ops_events.jsonl     # 本地运维事件备份
+-- .context/                # 项目上下文 (本文件)
```
