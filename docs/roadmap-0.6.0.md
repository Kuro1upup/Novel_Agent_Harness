# 0.6.0 质量审校与修订闭环

## 版本定位

0.6.0 在 0.5.0「章节中心写作台」和 0.5.1「本地运行可靠性补丁」之上，把已有的
连续性检查、事实风险、长期记忆冲突、草稿修订、Story Bible 版本快照和 Agent 运行
记录整合为作者可操作的审校闭环。

本版本仍面向本地个人使用，不纳入生产级账号、充值、多人协作或发布流水线。

## 已完成范围

### 1. 统一质量审校队列

- 新增 `QualityReviewService`，聚合 `continuity_issues`、`fact_risks` 和
  `memory_conflicts`。
- 三类问题统一暴露为 `QualityIssue`，包含类型、严重级别、状态、章节/草稿关联、
  证据、建议和处理说明。
- 支持按问题类型、处理状态、草稿和章节过滤。
- 支持 `open`、`resolved`、`ignored` 三种处理状态。

### 2. 从问题触发修订

- 新增 `/quality/issues/{issue_id}/revise`。
- 关联草稿的问题可以直接生成新修订草稿。
- 修订仍沿用原有草稿版本链：新草稿记录 `parent_draft_id` 和递增
  `revision_number`，不会覆盖原稿或已接受正文。

### 3. Story Bible 版本浏览与差异

- 新增 Story Bible 版本列表接口。
- 新增指定版本读取接口。
- 新增两个 Story Bible 版本的统一差异接口。
- Web 审校中心可以选择两个版本查看 Canon 变化。

### 4. Web 审校中心

- 新增「审校中心」导航页。
- 展示质量问题摘要、筛选器、问题列表和问题详情。
- 支持标记解决、忽略和重新打开。
- 支持从问题生成修订草稿。
- 展示 Story Bible 版本差异。
- 展示最近 Agent 运行耗时、模型、Prompt 版本和 Token 摘要。

## 数据迁移

迁移 `20260630_0009` 为以下表增加 `status` 索引字段：

- `continuity_issues`
- `fact_risks`
- `memory_conflicts`

历史记录默认视为 `open`。问题详情中的处理说明和处理时间保存在 JSON payload 中。

## API

- `GET /projects/{project_id}/quality/issues`
- `PATCH /quality/issues/{issue_id}`
- `POST /quality/issues/{issue_id}/revise`
- `GET /projects/{project_id}/bible/versions`
- `GET /projects/{project_id}/bible/versions/{version}`
- `GET /projects/{project_id}/bible/diff`

## 验收标准

- 连续性问题、事实风险和记忆冲突可以在同一审校队列中查看。
- 问题可以标记为已解决、已忽略或重新打开。
- 从关联草稿的问题发起修订会创建新草稿版本，不覆盖原草稿。
- Story Bible 历史版本可列出、读取并生成统一差异。
- Web 可以完成筛选问题、查看详情、处理状态、触发修订和查看版本差异。
- Python API 测试和 Web 构建通过。

## 继续延期

- OAuth 和手机号注册恢复。
- 充值接口重构。
- Python 到 Billing 的生产级持久化 Outbox 与后台补偿队列。
- 多人协作、分享审阅和角色权限。
- 生产级高可用、集中监控和自动发布流水线。
