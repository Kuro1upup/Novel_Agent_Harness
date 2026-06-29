# 0.5.1 本地运行可靠性补丁

## 版本定位

0.5.1 在 0.5.0 章节中心写作台之上，回补原 0.4.1 延期的本地账号初始化、Go 服务
统一检查和 Billing Redis 消息修复。由于 0.5.0 已完成并提交，本次按补丁版本发布为
0.5.1，不回退版本号。

## 已完成范围

### 1. 本地账号初始化

- 新增 `novel-harness db bootstrap-local-user`，无需邮件验证码即可创建已验证邮箱账号。
- 初始化接口要求共享内部 API Key，且 Auth 默认关闭；本地 Docker Compose 显式开启。
- 命令默认创建 `author@local.test`，交互读取密码，不在终端回显。
- 重复执行返回已有账号，不覆盖密码；只有 `--reset-password` 会明确重置。
- 默认把 `owner_user_id=0` 的历史作品分配给该账号，新账号仍沿用现有初始余额逻辑。

### 2. Go 服务统一检查

- Auth 与 Billing Dockerfile 新增 `check` 阶段。
- `make check` 统一执行 Go 格式检查、`go vet` 和单元测试。
- Go 检查使用容器化工具链，本地无需单独安装 Go，但需要 Docker。

### 3. Billing 消息可靠消费

- Redis 用量消息仅在数据库处理成功后 ACK，处理失败时保留在 pending 队列。
- 每轮消费先重试当前消费者的 pending 消息，再读取新消息。
- Redis Stream 消息 ID 写入 `event_id` 唯一键，重复投递不会重复计费。
- 原始用量记录与月账单更新放在同一事务中，避免只写入一半。
- 非 Redis 的 HTTP 用量上报接口保持兼容，充值接口不变。

## 升级方式

```bash
make local-up
novel-harness db migrate
make local-bootstrap
```

Billing 服务启动时会幂等增加 `token_usage_records.event_id` 和唯一索引，无需新增
Python Alembic 迁移。实际 `.env` 与 `auth/.env` 需要包含：

```dotenv
LOCAL_ACCOUNT_BOOTSTRAP_ENABLED=true
```

## 验收标准

- 未开启本地初始化或内部密钥错误时，Auth 拒绝初始化请求。
- 首次执行初始化创建账号，重复执行不新增账号且不重置密码。
- 历史未归属作品在初始化后归属于本地账号。
- Billing 数据库失败时消息不 ACK；恢复后 pending 消息可重试。
- 同一 Redis 消息重复处理时只产生一条用量记录和一次月账单增量。
- Python、TypeScript、Auth Go、Billing Go 的测试与静态检查全部通过。

## 继续延期

- OAuth 和手机号注册。
- Python 到 Billing 的生产级持久化 Outbox。
- 充值接口重构、多人协作和生产级发布能力。
