# 0.3.0 开发计划

## 目标

0.3.0 将已接入的 Auth/Billing 基础能力扩展为可持续使用的多租户创作工作台。版本重点
不是增加更多 Agent，而是补齐账户、作品和费用三个产品闭环。

## 交付范围

### 1. 多租户与账户

- 所有业务 API 强制校验 Auth Token。
- 项目及项目子资源按 Auth 用户 ID 隔离。
- Web 支持注册、登录、登录态恢复和退出。

### 2. 项目生命周期

- 已登录用户可在任意时刻创建新作品。
- 支持修改作品名、类型、读者、基调和梗概。
- 支持无损归档和恢复；归档不删除 MySQL、MinIO 或 Milvus 数据。
- 归档作品拒绝新的生成、编辑和工作流操作。
- 历史项目通过显式 CLI 命令分配所有者，不自动授予第一个注册用户。

### 3. 计费闭环

- Agent 调用前检查账户余额，余额小于或等于 0 时拒绝生成。
- Agent 成功后按用户、模型和子系统上报输入/输出 Token。
- Web 展示余额、累计充值、累计消费、每日用量、月度账单和充值记录。
- Auth、Billing、API 使用共享内部 API Key，内部 Billing 路由不对网关暴露。

### 4. 部署与质量

- MySQL 使用 `novel_agent`、`novel_auth`、`novel_billing` 三个独立数据库。
- Docker Compose 负责数据库初始化、迁移和全部应用服务编排。
- Python、TypeScript、Go 镜像和 Alembic 模型迁移均纳入发布检查。

## 验收标准

- 用户 A 无法列出或访问用户 B 的项目及子资源。
- 归档项目不出现在默认项目列表，且生成接口返回 `project_archived`。
- 恢复后原有 Story Bible、草稿、记忆和工作流仍可访问。
- 余额为 0 时，LLM Provider 不会被调用。
- Billing 页面数据与 `/api/billing/*` 返回一致。
- `pytest`、Ruff、Mypy、前端 lint/build 和 `alembic check` 全部通过。

## 后续版本候选

0.4.0 可继续处理协作与发布能力：项目成员/角色、分享审阅、章节导出包、通知中心和
Billing 用量幂等 Outbox。以上内容不纳入 0.3.0，避免破坏当前单作者 Canon 工作流。
