# CLAWS 已知问题

## 活跃问题

### 1. config 目录双重来源

- **症状**: Dockerfile 中 `COPY config/ config/` 将 Prompt 打入镜像，但 Prompt 修改后需要重建镜像才能生效
- **风险**: 忘记重建镜像会导致容器内运行旧版 Prompt
- **建议**: 考虑改为 volume 挂载 config 目录

### 2. memory 目录无清理机制

- **症状**: 每日产生 raw/filtered/deep-dives/reflections/reviews/state 等文件，长期运行会累积
- **影响**: 磁盘空间缓慢增长，SQLite 索引也会持续增大
- **建议**: 增加定期清理策略（如保留最近 30 天）

### 3. Knot 平台 MCP 未配置

- **症状**: 4 个 Agent 均未配置 MCP 服务，依赖 web_search 进行信息采集
- **影响**: 无法使用结构化 API（如 GitHub API）获取精确数据
- **建议**: 人工到 Knot 平台 Web UI 为 Scout/Analyst/Reviewer 配置推荐的 MCP

## 已解决问题

### 4. Scout Agent 输出不稳定 (2026-03-01 修复)

- deepseek-v3.2 偶尔在 JSON 前输出思考过程，约 10-15% 调用
- 修复: extract_json 迁移到 json_repair 第三方包 + Prompt 格式约束加强
- 监控: ops_reporter 上报 json_parse_failed 事件
- v3 增强: Pipeline 状态机记录失败并支持自动重试

### 5. Evolve Agent 与 Runner 文件写入冲突 (2026-02-28 修复)

- 修复: Runner 是唯一文件写入者，Agent 只输出 JSON

### 6. 飞书推送格式不一致 (2026-03-01 修复)

- v2 问题: 5 个推送点各自拼接字符串，格式不统一，Markdown 语法在纯文本中不渲染
- v3 修复: 统一为 5 个纯文本模板函数 (_fmt_sense/_fmt_dive/_fmt_reflect/_fmt_review/_fmt_weekly)
- 所有推送改用 feishu_text，不再使用 feishu_card 的 interactive 模式

### 7. 推送无结构信息 (2026-03-01 修复)

- v2 问题: 周报直接截取 result["content"][:2000]，反思推送使用 push_parts 拼接
- v3 修复: 从 JSON 结构提取关键字段，使用标准化模板格式化

### 8. 飞书推送多层截断 (2026-03-02 修复)

- v3 问题: 三层截断导致飞书报告不完整 — _PUSH_MAX_LEN=2000 全局截断 + meta_observation[:200] 字段截断 + _truncate() 强制截尾
- 表现: 侦察报告趋势分析被截断、深度分析只显示前 800 字、反思报告 Evolve 内容被砍至 300 字
- 修复: 提升限额(4000) + 提升字段阈值(meta 600/dive 2000/evolve 600) + 移除 _truncate + 新增 _split_message 分段发送
