COMPOSE ?= docker compose
BACKUP ?= backups/novel-$(shell date +%Y%m%d-%H%M%S).tar.gz

.PHONY: local-up local-down local-status local-logs local-migrate local-bootstrap local-backup check go-check

local-up:
	$(COMPOSE) up -d --build

local-down:
	$(COMPOSE) down

local-status:
	$(COMPOSE) ps

local-logs:
	$(COMPOSE) logs -f api worker auth billing web

local-migrate:
	.venv/bin/novel-harness db migrate

local-bootstrap:
	$(COMPOSE) exec api novel-harness db bootstrap-local-user

local-backup:
	mkdir -p backups
	.venv/bin/novel-harness ops backup $(BACKUP)
	.venv/bin/novel-harness ops verify $(BACKUP)

check:
	.venv/bin/pytest -q
	.venv/bin/ruff check src tests migrations
	.venv/bin/ruff format --check src tests migrations
	.venv/bin/mypy src/novel_harness
	cd web && npm run lint && npm run build
	$(MAKE) go-check

go-check:
	docker build --target check ./auth
	docker build --target check ./billing
