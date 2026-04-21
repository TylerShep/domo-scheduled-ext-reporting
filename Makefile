# Makefile for Docker Dev Workflow
PROJECT_NAME=domo-scheduled-ext-reporting
SERVICE=app

.PHONY: help up down build shell run re-run logs test lint format ps clean clean-all scheduler list validate scaffold

help: ## Show all commands
	@echo "Usage: make [command]"
	@echo ""
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## ' Makefile | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

up: ## Start all docker services in detached mode
	docker compose up -d

down: ## Stop all docker services
	docker compose down

build: ## Build docker image without using cache
	docker compose build --no-cache

shell: ## Open a shell session inside the app container
	docker compose exec $(SERVICE) bash

run: up ## Alias for "up"

re-run: ## Rebuild and restart all services
	$(MAKE) down
	$(MAKE) build
	$(MAKE) up

logs: ## View logs for the app service
	docker compose logs -f $(SERVICE)

test: ## Run pytest test suite inside the container
	docker compose exec $(SERVICE) pytest

lint: ## Run ruff linter inside the container
	docker compose exec $(SERVICE) ruff check app tests

format: ## Format code with black
	docker compose exec $(SERVICE) black app tests main.py

ps: ## Show running containers
	docker compose ps

# ---- Application commands (run inside container) ----

list: ## List all registered reports (LIST="report1 report2")
	docker compose exec $(SERVICE) python main.py --list $(LIST)

scheduler: ## Start the in-container APScheduler (blocks)
	docker compose exec $(SERVICE) python main.py --scheduler

validate: ## Parse and validate every config/reports/*.yaml without sending
	docker compose exec $(SERVICE) python main.py --validate

scaffold: ## Generate a new YAML report stub (NAME=my_report)
	docker compose exec $(SERVICE) python main.py --scaffold --name $(NAME)

# ---- Cleanup ----

clean: ## Stop and remove this project's docker resources
	docker compose -p $(PROJECT_NAME) down --rmi all --volumes --remove-orphans

clean-all: ## Nuclear: remove ALL docker containers/images/volumes/networks
	@echo "Stopping all containers..."
	docker ps -aq | xargs -r docker stop
	@echo "Removing all containers..."
	docker ps -aq | xargs -r docker rm -v
	@echo "Removing all images..."
	docker images -aq | xargs -r docker rmi -f
	@echo "Removing all volumes..."
	docker volume ls -q | xargs -r docker volume rm
	@echo "Removing custom networks..."
	docker network ls --filter 'type=custom' -q | xargs -r docker network rm
	docker system prune -a --volumes --force
