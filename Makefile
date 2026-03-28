.PHONY: install dev lint test up down

install:
	@echo "Install dependencies for each app (placeholder)"

dev:
	@echo "Run API and web in development mode (placeholder)"

lint:
	@echo "Run linters across the monorepo (placeholder)"

test:
	@echo "Run test suites across the monorepo (placeholder)"

up:
	docker compose -f infra/docker/docker-compose.yml up --build -d

down:
	docker compose -f infra/docker/docker-compose.yml down
