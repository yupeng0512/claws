# CLAWS 开发进度

## 当前版本: v3 (Runner v3)

## 历史演进

### Phase 1: OpenClaw 原型 (2026-02 初)
- [x] 基于 OpenClaw 框架的初始版本
- [x] 单 Agent 探索
- [x] 放弃原因: 外部 API 成本过高

### Phase 2: Knot Agent 迁移 (2026-02-28)
- [x] 迁移到 Knot Agent 平台 (零成本)
- [x] 多 Agent Pipeline 架构设计
- [x] Scout + Analyst + Evolve 三 Agent 实现
- [x] APScheduler 本地调度
- [x] 品味自进化机制 (TASTE.md 自改写)
- [x] 飞书推送集成
- [x] Ops Dashboard 告警接入

### Phase 3: 完整闭环 (2026-02-28)
- [x] Reviewer Agent (自动反馈回路)
- [x] 商业可行性评估维度
- [x] Docker 容器化 7x24 部署
- [x] 日志轮转 (10MB x 5)
- [x] JSON 解析迁移到 json_repair 第三方包
- [x] Flow Webhook 兼容
- [x] 品味进化 v0.1.0 -> v0.1.3 验证

### Phase 4: v3 增强 (2026-03-01)
- [x] 推送格式规范化: 5 种场景统一纯文本模板 (feishu_text)
- [x] Pipeline 状态机: 断点恢复 + Phase 依赖检查 + 失败重试 (pipeline_state.py)
- [x] 会话持久化: conversation_id 复用 + 每周自动重置 (SessionManager)
- [x] 记忆系统: SQLite FTS5 全文检索 + 时间衰减 (memory_store.py)
- [x] 预注入上下文: 运行统计 + 记忆检索结果自动注入 prompt
- [x] 自进化增强: 周度系统统计注入 Evolve prompt
- [x] 修正 Knot Agent 能力认知: 平台已具备 Shell/浏览器/MCP/Skills
- [x] agents.yaml 记录 MCP 推荐配置
- [x] .context 文档全面更新

#### v3 关键架构决策
- 废弃 Tool Mediator 方案: Knot Agent 自身已有 tool loop + 命令执行
- Runner 角色重新定义: 专注编排/状态/推送/记忆/自进化，不重造工具能力
- 能力扩展路径: 通过 Knot 平台 Web UI 配置 MCP/Skills

### Phase 5: 推送完整性修复 (2026-03-02)
- [x] 飞书推送截断修复: _PUSH_MAX_LEN 2000 -> 4000
- [x] 字段级截断阈值提升: meta_observation 200->600, dive preview 800->2000, push_to_human 300->600
- [x] 移除所有 _fmt_* 函数的 _truncate() 调用，返回完整内容
- [x] 新增 _split_message() 分段发送机制，超长消息按段落边界拆分为多条
- [x] feishu_text() 支持自动分段发送 (带序号标记)
- [x] 侦察报告模板优化: 先摘要再详情，展示筛选理由

## 待优化项

### 高优先级
- [ ] config 目录挂载策略统一 (Dockerfile COPY vs volume mount)
- [ ] 调度节奏应从 agents.yaml schedule 配置中读取，而非硬编码
- [ ] 为 Scout/Analyst/Reviewer 配置 Knot 平台 MCP 服务 (人工操作)

### 中优先级
- [ ] memory 目录增加清理策略 (保留 30 天)
- [ ] 增加 HTTP API 接口 (查询今日发现、手动触发阶段、查看调度状态)
- [ ] 品味模型版本回滚能力
- [ ] Pipeline 状态可视化 (Web Dashboard)

### 低优先级
- [ ] Web Dashboard 展示发现和品味进化趋势
- [ ] Knot Agent Skills 配置评估
