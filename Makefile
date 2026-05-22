# FinOps Down-Scaler — developer shortcuts
# Run `make` with no arguments to see available commands.

.PHONY: demo dev dev-win build test stop logs clean help
.DEFAULT_GOAL := help

# ── Entry points ─────────────────────────────────────────────────────────────

demo: ## ▶  Start dashboard in demo mode  →  http://localhost:8090
	@printf "\n  \033[32mFinOps Dashboard — demo mode\033[0m\n"
	@printf "  Synthetic data · no Kubernetes or Prometheus needed.\n"
	@printf "  Open \033[36mhttp://localhost:8090\033[0m once the build finishes.\n\n"
	DEMO_MODE=true docker compose up --build

full: ## ▶  Start dashboard + controller (requires .env with cluster config)
	@printf "\n  \033[33mFinOps Dashboard — full mode\033[0m\n"
	@printf "  Make sure .env is configured (see .env.example).\n\n"
	docker compose --profile full up --build

dev: ## ▶  Hot-reload dev servers  →  backend :8090  frontend :5173
	@bash scripts/dev.sh

dev-win: ## ▶  Hot-reload dev servers (Windows PowerShell)
	@powershell -ExecutionPolicy Bypass -File scripts/dev.ps1

# ── Build & test ─────────────────────────────────────────────────────────────

build: ## ⚙  Build the production frontend bundle
	cd dashboard/frontend && npm ci && npm run build
	@printf "\n  \033[32m✓\033[0m Frontend built to dashboard/frontend/dist/\n\n"

test: ## ✔  Run the full backend test suite
	pip install -q -r requirements-dev.txt
	pytest tests/ -v

# ── Lifecycle ─────────────────────────────────────────────────────────────────

stop: ## ■  Stop and remove containers
	docker compose --profile full down

logs: ## ⎙  Stream container logs (Ctrl+C to exit)
	docker compose --profile full logs -f

clean: ## 🗑  Remove containers, images, and build artefacts
	docker compose --profile full down --rmi local --volumes
	rm -rf dashboard/frontend/dist

# ── Help ─────────────────────────────────────────────────────────────────────

help: ## Show this help
	@printf "\n  \033[1mFinOps Down-Scaler\033[0m — available commands:\n\n"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@printf "\n"
