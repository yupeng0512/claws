# CLAWS 开发指南

## 环境变量

复制 `.env.example` 为 `.env`，填入实际值：

| 变量 | 必需 | 说明 |
|------|------|------|
| `KNOT_API_BASE_URL` | 是 | Knot Agent 平台地址 |
| `KNOT_API_TOKEN` | 是 | 个人 Token（一个 token 调所有 Agent） |
| `KNOT_WORKSPACE_UUID` | 是 | 云工作区 UUID（所有 Agent 共用） |
| `KNOT_SCOUT_AGENT_ID` | 是 | Scout Agent 的 Knot ID |
| `KNOT_ANALYST_AGENT_ID` | 是 | Analyst Agent 的 Knot ID |
| `KNOT_EVOLVE_AGENT_ID` | 是 | Evolve Agent 的 Knot ID |
| `KNOT_REVIEWER_AGENT_ID` | 是 | Reviewer Agent 的 Knot ID |
| `FEISHU_WEBHOOK_URL` | 否 | 飞书推送 Webhook |
| `OPS_DASHBOARD_URL` | 否 | 默认 `http://ops-dashboard:9090` |
| `CLAWS_SENSE_INTERVAL_HOURS` | 否 | 扫描间隔，默认 4 小时 |
| `CLAWS_TIMEZONE` | 否 | 时区，默认 `Asia/Shanghai` |

## 本地开发

```bash
# 安装依赖
pip install -r requirements.txt   # httpx, apscheduler, pyyaml

# 手动执行单个阶段（不启动调度器）
python claws_runner.py -p sense    # 侦察 + 筛选
python claws_runner.py -p dive     # 深度分析
python claws_runner.py -p reflect  # 反思 + 品味进化
python claws_runner.py -p review   # 独立审查
python claws_runner.py -p weekly   # 周报 + 大调整

# 守护进程模式（7×24 运行）
python claws_runner.py
```

## Docker 部署

```bash
cd /data/workspace/claws
docker compose build
docker compose up -d

# 查看日志
docker logs -f claws

# 查看调度状态
docker logs claws 2>&1 | grep -E "(Added job|Scheduler started|Phase)"
```

Admin Dashboard 通过 Traefik 反向代理访问：`http://claws.dev.local/`

Mac hosts 配置（如未添加）：
```bash
echo "<YOUR_MACHINE_IP> claws.dev.local" | sudo tee -a /etc/hosts
```

## Agent Prompt 修改

每个 Agent 的完整定义在 `config/agents/<name>/main.md`，格式为：

```markdown
---
name: Agent 名称
description: 描述
model: 模型名
---

## Prompt

(以下所有内容作为实际 Prompt 发送给 Agent)
```

修改 Prompt **无需重建 Docker 镜像**。`docker-compose.yml` 通过 `./config:/app/config:ro` 将 config 目录挂载到容器内，运行时覆盖镜像中 COPY 的默认值。修改 `config/agents/<name>/main.md` 后重启容器即可生效：

```bash
docker compose restart claws
```

同样，`TASTE.md` / `SOUL.md` / `CLAWS.md` 也通过 volume 挂载，即时生效。

## 调度配置

调度节奏从 `config/agents.yaml` 的 `schedule` 块读取，无需修改代码。修改 YAML 后重启容器即可生效：

```yaml
# config/agents.yaml — schedule 块示例
schedule:
  sense:
    agent: scout
    interval_hours: 4        # IntervalTrigger
  dive:
    agent: analyst
    cron: "0 10,22 * * *"    # CronTrigger (标准 5 字段)
```

时区通过环境变量 `CLAWS_TIMEZONE` 控制（默认 `Asia/Shanghai`）。

## 日志和监控

- **运行日志**: `logs/claws.log`（10MB × 5 轮转）
- **运维事件**: `logs/ops_events.jsonl`（本地备份）+ ops-dashboard（远程）
- **Docker 健康检查**: 120 秒间隔，检查 log 文件存在且非空
- **Ops 告警**: Agent 连续失败 3 次触发 critical 告警

## 品味模型迭代

TASTE.md 由 Evolve Agent 自主进化，人工也可以直接编辑：

1. 直接修改 `/data/workspace/claws/TASTE.md`（Docker volume 挂载，即时生效）
2. 或通过手动执行 `python claws_runner.py -p reflect` 触发一次进化
3. 变更历史在 `memory/taste-changelog.md`

## 关键技术决策

| 决策 | 选择 | 原因 |
|------|------|------|
| AI 平台 | Knot Agent (非 OpenAI API) | 企业内部免费，零成本 |
| 调度 | 本地 APScheduler (非 Cron) | 异步友好，misfire 处理，max_instances=1 防重入 |
| Scout 模型 | claude-4.6-sonnet | 当前统一模型，减少认知分裂 |
| 分析/审查模型 | claude-4.6-sonnet | 深度推理能力强 |
| 文件存储 | 本地 Markdown (非数据库) | 简单、可 Git 追踪、Agent 可直接读写 |
| 写入者 | Runner 独占 (Agent 只输出 JSON) | 避免 Agent 云工作区与本地文件冲突 |
