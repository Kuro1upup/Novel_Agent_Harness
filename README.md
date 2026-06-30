# Novel Agent Harness

面向长篇网文创作的 Provider 中立智能体底座。它把作者样文、资料研究、长期
Story Bible、剧情规划、章节生成、连续性检查和事实检查组织为一套可测试的工作流，
同时提供 Typer CLI 与 FastAPI。

本项目是独立实现，不包含或依赖任何泄露源码、未授权源码或商业闭源项目源码。

## 能力

- 从作者有权使用的样文中提取叙事视角、句段长度、对白比例、修辞、节奏和续写约束。
- 通过 SearXNG 搜索资料，保存来源、可信度、不确定性和写作含义。
- 安全抓取公开网页正文，提取带 URL、位置和内容哈希的证据片段，并做跨来源印证。
- 使用 Milvus 检索相关设定、人物、章节、研究证据和文档片段后再规划与写作。
- 版本化维护人物、规则、地点、势力、时间线、伏笔、悬念和 canon 事件。
- 生成至少三个下一阶段剧情方案。
- 输出章节正文、创作说明、事实依据摘要和待研究主题。
- 检查人物年龄/动机、世界规则、时间线、伏笔和现实事实风险。
- 草稿只生成 `CanonPatch`，作者显式接受后才更新 Story Bible。
- 将研究、规划、写作、审校和 Canon 提交作为可恢复的 MySQL 持久化工作流执行。
- 支持步骤重试、人工/自动审批、取消、项目内幂等创建和完整事件审计。
- 从已接受章节提取带 Canon 版本和正文来源的长期叙事记忆。
- 结合 Qwen 向量、关键词 RRF 和结构化过滤检索人物、地点、物品与事件状态。
- 写作前检查人物位置、物品归属和年龄等跨章节冲突。
- 检测与导入样文的长连续片段和 n-gram 重叠，降低复刻风险。
- 由人物、世界观和伏笔 Agent 生成提案，并由作者显式决定是否写入 Canon。
- 比较剧情候选并锁定方案，所选方案会随草稿和工作流全程保留。
- 管理草稿读取、下载、拒绝、按意见修订、版本血缘和统一差异。
- 在审校中心统一处理连续性问题、事实风险和长期记忆冲突，并从问题直接生成修订稿。
- 提供 React Web 工作台以及 Agent 耗时、Token、成本和 Prompt 版本日志。
- 按 Auth 用户隔离作品，支持作品新建、编辑、无损归档与恢复。
- 提供账户级 Billing 中心，展示余额、Token 用量、月度账单和充值记录。
- 按卷和章节组织已审阅内容，并导出 Markdown、DOCX 或 ZIP 交付稿。
- 从章节直接启动生成工作流，自动维护当前草稿与已接受版本。
- 支持正文手工修订、DOCX 导出、字数统计和工作流自动刷新。

当前版本为 0.6.0：在章节中心写作台之上增加质量审校与修订闭环，统一处理连续性、
事实风险和长期记忆冲突，并提供 Story Bible 版本差异与 Agent 运行摘要。范围与验收
标准见 [`docs/roadmap-0.6.0.md`](docs/roadmap-0.6.0.md)。

## 架构

| 组件 | 职责 |
|---|---|
| MySQL 8 | 项目、版本化 Story Bible、研究记录、草稿元数据、审计记录 |
| MinIO | 原始文档、解析文本、章节正文和大型产物 |
| Milvus 2 | 按 `project_id` 隔离的文档与上下文向量 |
| Redis 7 | 可丢弃的版本化查询缓存与工作流事件通知；故障时自动降级 |
| Auth (Go) | 邮箱/手机号注册登录、JWT、用户资料；数据位于独立 `novel_auth` 库 |
| Billing (Go) | 余额、充值和 Token 用量账单；数据位于独立 `novel_billing` 库 |
| LLM Provider | 默认 DeepSeek `deepseek-v4-flash`，可切换 Mock/其他兼容接口 |
| Search Provider | Mock 或 SearXNG JSON Search API |
| Embedding Provider | 默认百炼 `text-embedding-v4` 1024 维；确定性实现用于离线测试 |

MySQL 是业务元数据的权威来源；正文和文件不重复存入 MySQL。跨 MySQL、MinIO、
Milvus 的写入使用 pending/ready 状态与补偿删除，避免不可追踪的半完成记录。

## 安装

要求 Python 3.11+、MySQL 8+、Milvus 2.x、MinIO；Redis 7 为可选加速层。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

本地开发可启动随项目提供的基础设施：

```bash
make local-up
make local-bootstrap
novel-harness infra check
novel-harness db init
```

`make local-bootstrap` 会在容器内提示输入本地账号密码，默认创建
`author@local.test`，并把 `owner_user_id=0` 的历史作品分配给该账号。已有账号的密码
默认不会改变；需要重置时使用
`novel-harness db bootstrap-local-user --reset-password`。
初始余额初始化使用幂等键，Billing 临时不可用时命令会失败，可在 Billing 恢复后重跑。

停止整套本地服务：

```bash
make local-down
```

`docker-compose.yml` 使用以下端口：

- MySQL：`localhost:3306`
- MinIO S3 API：`localhost:20000`
- MinIO Console：`localhost:20001`
- Milvus：`localhost:19530`
- Redis：`localhost:20005`
- Auth：`localhost:8001`（由 API 网关通过 `/api/auth/*` 转发）
- Billing：`localhost:8002`（由 API 网关通过 `/api/billing/*` 转发）
- API：`localhost:8000`
- Web：`localhost:5173`

MySQL 使用同一个实例中的三个数据库：`novel_agent` 保存创作数据，`novel_auth`
保存用户，`novel_billing` 保存余额和账单。`novel-harness db init` 会创建三个库；
默认兼容旧配置使用同一个受限应用账户，也可以为 Auth/Billing 配置独立库账号。

建议的本地 `.env`：

```dotenv
DATABASE_HOST=localhost
DATABASE_PORT=3306
DATABASE_NAME=novel_agent
DATABASE_ROOT_USER=root
DATABASE_ROOT_PASSWORD=root_password
DATABASE_USER=novel_agent
DATABASE_PASSWORD=novel_agent_password

AUTH_REQUIRED=true
AUTH_SERVICE_URL=http://localhost:8001
AUTH_INTERNAL_API_KEY=replace-with-an-auth-internal-secret
AUTH_DATABASE_NAME=novel_auth
AUTH_DATABASE_USER=novel_auth
AUTH_DATABASE_PASSWORD=novel_auth_password
PHONE_REGISTRATION_ENABLED=false
LOCAL_ACCOUNT_BOOTSTRAP_ENABLED=true

BILLING_ENABLED=true
BILLING_REQUIRED=true
BILLING_SERVICE_URL=http://localhost:8002
BILLING_INTERNAL_API_KEY=replace-with-a-shared-random-secret
BILLING_DATABASE_NAME=novel_billing
BILLING_DATABASE_USER=novel_billing
BILLING_DATABASE_PASSWORD=novel_billing_password

MINIO_ENDPOINT=localhost:20000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_SECURE=false
MINIO_BUCKET=novel-agent

MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=novel_chunks_qwen_v4_1024

CACHE_PROVIDER=redis
REDIS_HOST=localhost
REDIS_PORT=20005
REDIS_PASSWORD=myredissecret
REDIS_DATABASE=0

EMBEDDING_PROVIDER=qwen
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSION=1024
QWEN_API_KEY=your-qwen-key

LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=your-deepseek-key

SEARCH_PROVIDER=searxng
SEARXNG_BASE_URL=https://searxng.dsppt.site
RESEARCH_FETCH_ENABLED=true
```

root 数据库账户只由 `novel-harness db init` 使用。应用运行时使用权限受限的
`novel_agent` 账户。生产环境必须更换示例凭据并通过密钥管理系统注入。

Auth 与 Billing 必须使用相同的 `JWT_SECRET`。Python API 调用 Auth 内部管理接口时
使用 `AUTH_INTERNAL_API_KEY`，Auth 调用 Billing 以及 Python API 上报用量时使用
`BILLING_INTERNAL_API_KEY`。实际密钥只放在各自未跟踪的 `.env` 中。

## 本地开发

本项目可以直接连接已有的 MySQL、MinIO、Milvus、Redis 和 SearXNG，不要求使用
仓库中的 `docker-compose.yml`。开始前请确认 `.env` 中的连接地址、账户和密钥与
本地环境一致。

首次安装：

```bash
cd /home/gxl77/codex_dev
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

没有外部模型密钥时，可以在 `.env` 中使用离线 Provider：

```dotenv
LLM_PROVIDER=mock
EMBEDDING_PROVIDER=deterministic
SEARCH_PROVIDER=mock
CACHE_PROVIDER=none
CORS_ORIGINS=http://127.0.0.1:5173,http://localhost:5173
```

### 启动后端

首次启动或拉取到新迁移后，先升级数据库：

```bash
cd /home/gxl77/codex_dev
source .venv/bin/activate
novel-harness db migrate
```

本地直接运行 Go 服务：

```bash
(cd billing && go run ./cmd/server)
(cd auth && go run ./cmd/server)
```

两个服务启动后初始化本地账号：

```bash
novel-harness db bootstrap-local-user --email author@local.test
```

启动 FastAPI 开发服务器：

```bash
uvicorn novel_harness.api:app \
  --host 127.0.0.1 \
  --port 8000 \
  --reload
```

后端地址：

- API：`http://127.0.0.1:8000`
- Swagger：`http://127.0.0.1:8000/docs`
- 存活检查：`http://127.0.0.1:8000/health`
- 依赖就绪检查：`http://127.0.0.1:8000/health/ready`

### 启动前端

在第二个终端执行：

```bash
cd /home/gxl77/codex_dev/web
npm install
VITE_API_URL=http://127.0.0.1:8000 npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。

### 启动工作流 Worker

创建持久化章节工作流后，需要 Worker 执行队列任务。在第三个终端执行：

```bash
cd /home/gxl77/codex_dev
source .venv/bin/activate
novel-harness worker
```

调试单个步骤或处理完当前队列后退出：

```bash
novel-harness worker --once
novel-harness worker --drain
```

默认日志写入 `logs/novel-harness.log`。本地开发常用检查命令：

```bash
pytest
ruff check src tests migrations
ruff format --check src tests migrations
mypy src/novel_harness

cd web
npm run lint
npm run build
```

## CLI

```bash
novel-harness init "长安旧梦" --genre 历史 --sub-genre 西汉
novel-harness ingest-style PROJECT_ID samples/author-owned.docx
novel-harness research PROJECT_ID "西汉长安社会风俗"
novel-harness bible show PROJECT_ID
novel-harness bible add-character PROJECT_ID character.json
novel-harness bible add-foreshadowing PROJECT_ID "残缺的铜符"
novel-harness plan PROJECT_ID --current "主角抵达城外" --goal "进入长安"
novel-harness write PROJECT_ID --goal "主角第一次进入长安"
novel-harness write PROJECT_ID --chapter-id CHAPTER_ID --goal "主角第一次进入长安"
novel-harness check PROJECT_ID chapter.md
novel-harness draft accept DRAFT_ID
novel-harness vector rebuild PROJECT_ID

# 创建异步章节工作流；相同 idempotency key 不会重复创建
novel-harness workflow start PROJECT_ID \
  --goal "主角第一次进入长安" \
  --current "主角抵达城外" \
  --research-topic "西汉长安城门制度" \
  --idempotency-key chapter-001

# 常驻 Worker；也可用 --once 只处理一步，或 --drain 处理到队列为空
novel-harness worker
novel-harness workflow show RUN_ID
novel-harness workflow approve RUN_ID research_approval --note "资料可用"
novel-harness workflow approve RUN_ID plot_approval --note "采用方案一"
novel-harness workflow approve RUN_ID draft_approval --note "接受草稿"
novel-harness workflow retry RUN_ID
novel-harness workflow cancel RUN_ID

novel-harness memory query PROJECT_ID "主角目前位于哪里"
novel-harness memory extract PROJECT_ID DRAFT_ID
novel-harness memory invalidate MEMORY_ID --reason "作者修正设定"
novel-harness memory rebuild PROJECT_ID

novel-harness agent character PROJECT_ID --name "林川" --role "主角" --apply
novel-harness agent worldbuilding PROJECT_ID --goal "完善长安权力结构" --apply
novel-harness agent foreshadowing PROJECT_ID --scene-goal "进入未央宫" --apply

novel-harness bible add-rule PROJECT_ID "城门入夜关闭"
novel-harness bible add-faction PROJECT_ID faction.json
novel-harness bible add-location PROJECT_ID location.json
novel-harness bible add-timeline PROJECT_ID timeline.json
novel-harness bible resolve-foreshadowing PROJECT_ID ITEM_ID \
  --resolution "铜符证明密使身份"

novel-harness write PROJECT_ID --goal "通过城门" \
  --plan-id PLAN_ID --option-id OPTION_ID
novel-harness draft list PROJECT_ID
novel-harness draft show DRAFT_ID
novel-harness draft revise DRAFT_ID --instruction "减少巧合，强化主动选择"
novel-harness draft diff OLD_DRAFT_ID NEW_DRAFT_ID
novel-harness draft edit DRAFT_ID edited-chapter.md --note "作者手工调整节奏"
novel-harness draft reject DRAFT_ID --reason "节奏不符合预期"
```

`character.json` 示例：

```json
{
  "name": "林川",
  "role": "主角",
  "age": 20,
  "motivation": "寻找失踪密使",
  "speech_style": "克制、短句",
  "constraints": ["不会无故伤害平民"]
}
```

## API

启动服务：

```bash
uvicorn novel_harness.api:app --host 127.0.0.1 --port 8000
```

先通过统一 API 网关登录，再把 Token 用于业务请求：

```bash
TOKEN=$(curl -sS -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"login":"author@example.com","password":"your-password"}' | jq -r .token)

curl -X POST http://127.0.0.1:8000/projects \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"长安旧梦","genre":"历史","sub_genre":"西汉"}'

curl -X POST http://127.0.0.1:8000/projects/PROJECT_ID/style/analyze \
  -H "Authorization: Bearer $TOKEN" \
  -F 'files=@samples/style.txt'

curl -X POST http://127.0.0.1:8000/projects/PROJECT_ID/research \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"topic":"西汉长安市井生活","keywords":["长安","市集"]}'

curl -X POST http://127.0.0.1:8000/projects/PROJECT_ID/plot/plan \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"current":"主角抵达城外","goal":"进入长安"}'

curl -X POST http://127.0.0.1:8000/projects/PROJECT_ID/write \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"goal":"主角第一次进入长安","current":"主角抵达城外"}'

curl -X POST http://127.0.0.1:8000/projects/PROJECT_ID/workflows \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "goal":"主角第一次进入长安",
    "current":"主角抵达城外",
    "research_topic":"西汉长安城门制度",
    "idempotency_key":"chapter-001"
  }'
```

升级前已经存在的项目会以 `owner_user_id=0` 保留。`AUTH_REQUIRED=true` 时不会自动暴露给
任意新用户；注册并确认目标 Auth 用户 ID 后，显式执行一次：

```bash
novel-harness db assign-legacy-owner USER_ID --confirm
```

每次 Agent 调用会在执行前通过 Billing 检查余额，成功后按 Auth 用户 ID 上报输入和
输出 Token。Billing 不可用或余额为负时，新的生成调用会被拒绝；已完成的用量上报
使用 `agent-run:<trace_id>` 作为幂等键，瞬时失败会短暂重试，最终失败的调用会记录
`billing_usage_report_failed` 错误日志。

完整 OpenAPI 文档位于 `/docs`。`/health` 是进程存活检查，`/health/ready` 会检查
MySQL、MinIO 和 Milvus。

新增的作者闭环接口包括：

- `POST /projects/{id}/agents/character|worldbuilding|foreshadowing`；
- `POST /projects/{id}/bible/rules|factions|locations|timeline|foreshadowing`；
- `POST /projects/{id}/plot/plans/{plan_id}/select`；
- `GET /projects/{id}/drafts`、`GET /drafts/{id}` 和 `GET /drafts/{id}/download`；
- `POST /drafts/{id}/revise|reject|accept` 与 `GET /drafts/{from}/diff/{to}`；
- `GET /projects/{id}/agent-runs`。

## Web 工作台

`web/` 是 React 19、TypeScript 和 Vite 实现的作者工作台，包含项目概览、Story
Bible 编辑、人物/世界观/伏笔提案、剧情方案对比、审批队列、章节修订与版本差异、
长期记忆检索和 Agent 运行记录。

```bash
cd web
npm install
VITE_API_URL=http://localhost:8000 npm run dev

# 生产构建
npm run lint
npm run build
```

后端通过 `CORS_ORIGINS` 配置允许的 Web 来源，多个来源使用逗号分隔。

## 持久化工作流

`chapter_generation` 工作流按顺序执行：

1. 资料研究与研究审批；
2. 长期记忆预检；硬冲突进入人工审批；
3. 剧情规划与方案审批；
4. RAG 写作、连续性/事实检查和自动修订；
5. 质量门与草稿审批；
6. 接受 `CanonPatch`，再从已接受正文提取长期记忆。

没有 `research_topic` 时研究步骤会安全跳过。`auto_approve=true` 适合自动化回归，
但未验证研究或未通过质量门的草稿仍会强制等待人工审批；作者生产流程建议保留审批
节点。每个步骤单独记录状态、尝试次数、输入引用、输出引用、错误和起止时间。Worker
使用带租约的 `SELECT ... FOR UPDATE SKIP LOCKED` 领取任务，进程退出后其他 Worker
可在租约过期后继续执行。

相关 API：

- `GET /workflows/{run_id}`：查询步骤和事件；
- `POST /workflows/{run_id}/steps/{step_name}/approval`：批准或拒绝；
- `POST /workflows/{run_id}/retry`：从失败步骤或指定步骤重试；
- `POST /workflows/{run_id}/cancel`：请求取消。

## 长篇记忆

MySQL 保存记忆事实、来源草稿、Canon 版本、置信度和失效状态；Milvus 保存同一
`memory_id` 的 Qwen 向量。查询先按项目和有效状态隔离，再用 RRF 合并语义排名与
关键词排名。Redis key 包含 MySQL `memory_revision`，因此记忆更新后旧缓存自然失效。
Redis 不保存权威记忆，停机时查询自动回退到 MySQL 和 Milvus。

只有 `accepted` 草稿能够写入长期记忆。状态型记忆（位置、物品归属、人物状态、
关系和知识边界）被新 Canon 覆盖时，旧记录保留审计但从活动索引失效。

相关 API：

- `GET /projects/{project_id}/memory`；
- `GET /projects/{project_id}/memory/state`；
- `POST /projects/{project_id}/memory/query`；
- `POST /memory/{memory_id}/invalidate`；
- `POST /projects/{project_id}/memory/rebuild`。

## 真实 Provider

### DeepSeek LLM

```dotenv
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=your-secret
LLM_SUPPORTS_JSON_SCHEMA=false
```

适配器调用 `/chat/completions`。DeepSeek 使用 JSON Object 模式，返回后仍由
Pydantic 校验。其他支持严格 JSON Schema 的兼容服务可将
`LLM_SUPPORTS_JSON_SCHEMA=true`。

### Qwen Embedding

```dotenv
EMBEDDING_PROVIDER=qwen
EMBEDDING_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIMENSION=1024
QWEN_API_KEY=your-secret
```

适配器自动按每批最多 10 条调用 `/embeddings`，显式请求 1024 维 float 向量。
从旧的 384 维 collection 升级后需运行 `novel-harness vector rebuild PROJECT_ID`。

无外部密钥的离线开发可临时设置：

```dotenv
LLM_PROVIDER=mock
EMBEDDING_PROVIDER=deterministic
```

### SearXNG

```dotenv
SEARCH_PROVIDER=searxng
SEARXNG_BASE_URL=https://searxng.dsppt.site
```

适配器调用 `GET /search` 并设置 `format=json`。若实例关闭 JSON 格式、限流或部分
搜索引擎失败，会返回明确 Provider 错误或保留可用结果。Mock 搜索结果始终标记为
未验证，不能作为真实事实。

真实搜索会进一步抓取有限数量的公开 HTML/纯文本来源。抓取器限制响应大小和重定向，
拒绝 localhost、私网及保留地址，正文和搜索内容始终按不可信数据处理。

## 扩展

- 新 LLM：实现 `providers.llm.base.LLMProvider`。
- 新搜索：实现 `providers.search.base.SearchProvider`。
- 新向量数据库：实现 `providers.vectorstore.base.VectorStore`，所有查询必须强制
  `project_id` 隔离。
- 新对象存储：实现 `providers.objectstore.base.ObjectStore`，bucket 默认保持私有。
- 新 Agent：在 `agents/` 中实现规则优先的确定性能力和可选 LLM 增强，在
  `prompts/` 中提供同名 Prompt，并由 Service/Orchestrator 调用，不直接访问数据库。

所有 Provider 输出都应在领域边界转为 Pydantic 模型，Provider 不应包含创作业务逻辑。

## 数据迁移、测试和恢复

```bash
alembic upgrade head
pytest
pytest -m integration
ruff check src tests migrations
ruff format --check src tests migrations
mypy src/novel_harness
```

默认测试使用内存关系数据库和 fake MinIO/Milvus，不访问网络。`integration` 与
`live` 标记分别用于本地基础设施和真实 Provider。

真实 Provider 测试默认跳过，显式执行才会消耗额度：

```bash
RUN_LIVE_TESTS=1 pytest -m live tests/test_live_providers.py
```

备份需要同时覆盖：

1. MySQL 的 `novel_agent`、`novel_auth`、`novel_billing` 三个数据库 dump；
2. MinIO `novel-agent` bucket；
3. Milvus collection。

Milvus 可由 MySQL 文档元数据、长期记忆、已验证研究证据和 MinIO 解析文本重建；运行
`novel-harness vector rebuild PROJECT_ID` 可重建单项目索引。重建过程只写入
`fetched/corroborated`、可信度不低于 0.5 且不是验证码/访问验证页的研究证据。

### Agent 日志

每次 Agent 调用都会写入 `agent_runs`，并输出不含正文和完整 Prompt 的结构化日志：
`trace_id`、项目/工作流、Agent、Provider、模型、Prompt 内容哈希版本、耗时、输入/
输出 Token、估算成本和错误类型。通过以下配置开启带轮转的文件日志：

```dotenv
LOG_FILE=logs/novel-harness.log
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5
LLM_INPUT_COST_PER_MILLION=0
LLM_OUTPUT_COST_PER_MILLION=0
```

成本单价默认是 0，需按实际供应商账单填写每百万 Token 单价。

### 备份和恢复演练

备份包含主业务、Auth、Billing 三个 MySQL 数据库的一致性 dump、MinIO bucket 对象
和 SHA-256 清单。Milvus 是可重建索引，不作为权威备份。执行主机需要安装 MySQL 8
客户端：

```bash
novel-harness ops backup backups/novel-$(date +%F).tar.gz
novel-harness ops verify backups/novel-2026-06-29.tar.gz

# 恢复到隔离的演练数据库和 bucket，不覆盖生产数据
novel-harness ops drill backups/novel-2026-06-29.tar.gz \
  --target-database novel_agent_drill \
  --target-bucket novel-agent-drill \
  --confirm
```

演练后针对恢复项目执行 `novel-harness vector rebuild PROJECT_ID`。直接恢复需要
`novel-harness ops restore ARCHIVE --confirm`，执行前必须停止 API/Worker 写入。

## 容器部署

项目不要求使用本仓库的 Compose；可直接连接共享中间件。根目录 `Dockerfile` 同时
用于 API 和 Worker：

```bash
docker build --target api -t novel-harness-api:0.2.0 .
docker build --target worker -t novel-harness-worker:0.2.0 .
docker run --env-file .env -p 8000:8000 novel-harness-api:0.2.0
docker run --env-file .env novel-harness-worker:0.2.0

docker build -t novel-harness-web:0.2.0 \
  --build-arg VITE_API_URL=https://novel-api.example.com web
docker run -p 8080:80 novel-harness-web:0.2.0
```

API 收到终止信号后执行运行时资源清理；Worker 完成当前步骤后停止领取新任务。
`/health/ready` 失败会写入告警日志，容器健康检查使用 `/health`。Billing 的
`/api/health` 会额外返回 `redis_connected` 和 `usage_consumer_started`，用于判断
用量事件流是否处于降级状态。

## 安全、版权与限制

- 只导入作者拥有或获授权使用的文本。
- 风格分析只保留抽象特征，不能据此承诺生成结果在法律意义上“原创”。
- 相似性检查是辅助安全机制，不替代版权审查。
- Prompt 将检索内容和导入文本视为不可信数据，不执行其中指令。
- 网页抓取仅允许公开 HTTP(S) 地址，并执行 SSRF、内容类型和响应大小检查。
- 历史、法律、医学、新闻、职业流程等事实必须带来源或标记不确定；重要内容应由
  作者回到一手、官方或学术来源复核。
- 当前支持 txt、Markdown、docx 和可提取文本的 PDF；扫描 PDF 不包含 OCR。
- 当前定位为可信网络内的单用户服务，不含鉴权、多租户、限流或公网安全加固。
- 日志不记录密钥和完整作者原文；不要把 `.env` 提交到版本库。
