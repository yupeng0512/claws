# CLAWS — Continuous Learning And Working System

> 基于 Knot Agent (AG-UI) 的自主探索系统，品味自进化，7×24h 运行

## 架构

```
  APScheduler (本地调度器)
       │
       ├── Phase 1: Scout (claude-4.6-sonnet + web search)
       │   └── SENSE + FILTER → memory/raw/ + memory/filtered/
       │
       ├── Phase 2: Analyst (claude-4.6-sonnet + web search)
       │   └── DIVE → memory/deep-dives/
       │
       ├── Phase 3: Evolve (claude-4.6-sonnet)
       │   └── REFLECT → TASTE.md / SOUL.md 自进化
       │
       └── Phase 4: Reviewer (claude-4.6-sonnet + web search)
           └── REVIEW → 商业评估 + 品味审计 + 盲区检测
```

## 核心特性

- **品味自进化**：Evolve Agent 每日反思，自动调整品味模型权重
- **自动反馈回路**：Reviewer Agent 替代人工反馈，提供独立审查信号
- **商业可行性评估**：Analyst 对每个发现做 TAM/MVP/对标分析
- **多模型策略**：便宜模型扫描 + 强模型分析，优化成本
- **生产级运维**：飞书推送、Ops Dashboard 告警、日志轮转、Docker 部署

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 配置 .env（从 .env.example 复制并填入你的 Agent ID 和 Token）
cp .env.example .env

# 手动运行各阶段
python claws_runner.py -p sense      # 侦察
python claws_runner.py -p dive       # 深挖
python claws_runner.py -p reflect    # 反思+进化
python claws_runner.py -p review     # 独立审查
python claws_runner.py -p weekly     # 周报

# 守护进程（7×24h）
python claws_runner.py

# Docker 部署
docker-compose up -d
```

## 项目结构

```
claws/
├── claws_runner.py          # 主程序（Pipeline 引擎 + 调度器）
├── ops_reporter.py          # Ops Dashboard 事件上报 SDK
├── CLAWS.md                 # 系统设计文档
├── TASTE.md                 # 品味模型（自进化）
├── SOUL.md                  # 探索者灵魂（身份定义）
├── config/
│   ├── agents.yaml          # Agent 架构配置
│   └── agents/
│       ├── scout/main.md    # 侦察兵 Agent 定义
│       ├── analyst/main.md  # 分析师 Agent 定义
│       ├── evolve/main.md   # 进化者 Agent 定义
│       └── reviewer/main.md # 审查者 Agent 定义
├── memory/
│   ├── DISCOVERIES.md       # 发现库
│   ├── taste-changelog.md   # 品味进化日志
│   ├── raw/                 # 原始扫描数据
│   ├── filtered/            # 筛选结果
│   ├── deep-dives/          # 深度分析报告
│   ├── reflections/         # 反思记录
│   ├── reviews/             # 审查报告
│   └── feedback/            # 反馈信号
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## 调度

| 阶段 | Agent | 频率 | 说明 |
|------|-------|------|------|
| SENSE | Scout | 每 4 小时 | 多源信息采集 + 品味初筛 |
| DIVE | Analyst | 每日 10:00, 22:00 | 深度分析 + 商业评估 |
| REFLECT | Evolve | 每日 21:00 | 反思 + 品味自进化 |
| REVIEW | Reviewer | 每日 21:30 | 独立审查 + 反馈生成 |
| WEEKLY | Evolve | 周日 15:00 | 周度大反思 + 品味大调整 |
