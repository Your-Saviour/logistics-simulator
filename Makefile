APP ?= storage
COMPOSE = docker compose -f deploy/generated/$(APP).json
TEST_COMPOSE = docker compose -f deploy/test.compose.yml

.PHONY: configure build up down suite test federation-test web-check smoke recovery check clean-tests credentials schema-check
configure:
	python3 scripts/compose.py
build: configure
	$(COMPOSE) build
up: configure
	$(COMPOSE) up -d --build --wait
suite:
	$(MAKE) up APP=suite
down:
	$(COMPOSE) down
test:
	$(TEST_COMPOSE) run --build --rm tests
federation-test:
	$(TEST_COMPOSE) run --build --rm tests python examples/helics/smoke.py
web-check:
	npm ci --prefix apps/web
	npm run build --prefix apps/web
	npm audit --prefix apps/web --audit-level=moderate
smoke:
	python3 scripts/smoke.py $(APP)
recovery:
	python3 scripts/recovery.py
schema-check:
	$(TEST_COMPOSE) run --build --rm tests python scripts/check_contracts.py
check: test schema-check federation-test web-check configure
	python3 scripts/check_compose.py
clean-tests:
	$(TEST_COMPOSE) down
credentials:
	python3 scripts/credentials.py $(APP)
