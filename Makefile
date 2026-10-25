APP ?= storage
.DEFAULT_GOAL := configure
COMPOSE = docker compose -f deploy/generated/$(APP).json
TEST_COMPOSE = docker compose -f deploy/test.compose.yml

.PHONY: configure build up down suite test federation-test web-check smoke recovery check clean-tests credentials schema-check stack-unit stack-check mixed-check storage-connected-check storage-deployment-check logistics-connected-check logistics-deployment-check manufacturing-connected-check manufacturing-deployment-check shipping-deployment-check shipping-connected-check twin-deployment-check handling-carrier-check
handling-factory-check:
	sh scripts/check_handling_factory.sh
handling-ui-check:
	sh scripts/check_handling_ui.sh
.PHONY: handling-ui-check
.PHONY: handling-factory-check
handling-carrier-check:
	sh scripts/check_handling_carrier.sh
handling-material-check:
	sh scripts/check_handling_material.sh
.PHONY: handling-material-check
stack-unit:
	sh scripts/check_stack_unit.sh $(APP)
stack-check:
	sh scripts/check_stacks.sh $(APP)
storage-deployment-check:
	sh scripts/check_storage_deployment.sh
storage-connected-check:
	sh scripts/check_storage_connected.sh
logistics-connected-check:
	sh scripts/check_logistics_connected.sh
logistics-deployment-check:
	sh scripts/check_logistics_deployment.sh
manufacturing-connected-check:
	sh scripts/check_manufacturing_connected.sh
manufacturing-deployment-check:
	sh scripts/check_manufacturing_deployment.sh
shipping-deployment-check:
	sh scripts/check_shipping_deployment.sh
shipping-connected-check:
	sh scripts/check_shipping_connected.sh
twin-deployment-check:
	sh scripts/check_twin_deployment.sh
mixed-check:
	sh scripts/check_mixed_stacks.sh
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
	docker build --target build --build-arg SIMULATOR=storage -t logistics-simulator:web-check -f apps/web/Dockerfile .
	docker run --rm logistics-simulator:web-check npm audit --audit-level=moderate
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

.PHONY: handling-performance-check
handling-performance-check:
	sh scripts/check_handling_performance.sh
