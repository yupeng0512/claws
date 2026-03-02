# CLAWS 项目上下文

本文件夹用于管理 CLAWS 项目的开发上下文，确保：

1. **切换 IDE/开发工具** 时能快速了解项目全貌
2. **切换 AI 模型/Session** 时能无缝继续开发
3. **新协作者** 接入时有完整的参考资料

## 文件索引

| 文件 | 内容 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构、技术栈、Agent Pipeline、部署拓扑 |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | 已知问题、临时方案、修复记录 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 环境变量、本地开发、部署流程、技术决策 |
| [PROGRESS.md](PROGRESS.md) | 开发进度、版本历史、待优化项 |

## 快速了解

CLAWS 是一个 **7×24 自主运行** 的技术趋势发现系统：
- 4 个 AI Agent (Scout/Analyst/Evolve/Reviewer) 通过 Knot Agent 平台调用
- APScheduler 容器内调度：每 4h 扫描、每日 10/22 点深挖、21 点反思、21:30 审查、周日周报
- 品味自进化：Evolve Agent 输出 JSON → Runner 写入 TASTE.md
- Docker 容器化部署，日志和 memory 通过 volume 持久化
