.PHONY: build up-test down-test test lint scan

build:
	docker build --platform=linux/amd64 -t local/wazuh-manager:latest docker/manager
	docker build --platform=linux/amd64 -t local/wazuh-dashboard:latest docker/dashboard

up-test:
	docker compose -f stack/wazuh-stack.yml -f stack/compose.test.override.yml up -d

down-test:
	docker compose -f stack/wazuh-stack.yml -f stack/compose.test.override.yml down -v

test:
	pytest -q

lint:
	yamllint . || true
	ansible-lint || true

scan:
	trivy image --severity HIGH,CRITICAL --exit-code 1 local/wazuh-manager:latest || true
