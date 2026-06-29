# 运维与恢复手册

## 运行拓扑

API 和 Worker 使用同一个镜像、同一套环境变量，并连接现有 MySQL、MinIO、Milvus
和可选 Redis。Auth 与 Billing 使用独立 Go 镜像。三个业务组件共享一个 MySQL 实例，
但分别使用 `novel_agent`、`novel_auth`、`novel_billing` 数据库。API 与 Worker
可以独立扩缩容；迁移只在发布阶段执行一次。

```bash
novel-harness db migrate
(cd billing && go run ./cmd/server)
(cd auth && go run ./cmd/server)
uvicorn novel_harness.api:app --host 0.0.0.0 --port 8000
novel-harness worker
```

发布检查必须确认 Auth/Billing 的 `JWT_SECRET` 一致。Python API 调用 Auth 内部管理
接口使用 `AUTH_INTERNAL_API_KEY`，Auth 调用 Billing 以及 Python API 上报用量使用
`BILLING_INTERNAL_API_KEY`。`/health/ready` 会把 Auth 和 Billing 纳入必需依赖。

升级到 0.5.1 后执行 `novel-harness db migrate` 并重启 Auth/Billing。Billing 启动时
会为用量表和充值表增加幂等事件键；Python 迁移继续维护章节、当前草稿与已接受版本。
归档是无损操作，不删除对象、向量或关联关系；归档项目上的新工作流和生成请求会被拒绝。

本地整套服务可使用 `make local-up` 启动、`make local-down` 停止，使用
`make local-status` 查看状态。

首次本地运行执行 `make local-bootstrap`，交互输入至少 8 位密码。该命令通过内部
密钥调用 Auth，只创建已验证邮箱账号，并把未归属历史作品分配给该用户。Auth 二进制
默认关闭此能力；Docker Compose 的本地配置通过
`LOCAL_ACCOUNT_BOOTSTRAP_ENABLED=true` 显式开启。已有密码只有传入
`--reset-password` 时才会替换。初始余额写入是幂等操作；如果 Billing 临时不可用，
`make local-bootstrap` 会失败，恢复后重跑即可补齐余额。

`make check` 会通过两个 Go Dockerfile 的 `check` 阶段运行 `gofmt`、`go vet` 和
`go test`，因此执行完整检查需要 Docker。

## 日志与告警

生产环境建议同时收集容器标准错误流和 `LOG_FILE`。日志不包含正文、导入样文、完整
Prompt 或密钥。至少对以下事件建立告警：

- `readiness_failed`；
- `agent_failed`；
- `step_failed`、`run_failed`；
- Worker 在预期运行时间内没有 `worker_started` 或工作流事件。
- Billing 日志中的 `left pending for retry`，表示用量消息写入失败并等待重试。

成本告警以 `agent_succeeded.estimated_cost` 聚合；只有配置真实模型单价后该字段才有
财务意义。

## 优雅停机

API 停止时关闭已构造的 Provider 客户端和数据库 Engine。Worker 收到 SIGINT/SIGTERM
后不再领取新任务，并等待当前步骤结束。部署平台的 termination grace period 应大于
单次 LLM 请求超时与重试窗口之和。

## 备份策略

每日运行 `novel-harness ops backup`，随后运行 `ops verify`。备份包含
`novel_agent`、`novel_auth`、`novel_billing` 三个数据库，应复制到与 MinIO 故障域
不同、启用版本控制和生命周期策略的存储。数据库 dump 使用
`--single-transaction`；运行主机需安装 MySQL 8 的 `mysqldump`/`mysql` 客户端，
备份账户需要读取三个数据库和 bucket 的权限。

个人本地部署可以直接运行 `make local-backup`，归档默认写入 `backups/`。

每月至少执行一次：

```bash
novel-harness ops drill ARCHIVE \
  --target-database novel_agent_drill_YYYYMM \
  --target-bucket novel-agent-drill-yyyymm \
  --confirm
```

验证项目、Story Bible、草稿对象和工作流记录后，为抽样项目执行向量重建与记忆查询。
演练资源确认无误后按基础设施流程删除，不能使用生产数据库或 bucket 作为 drill 目标。
