# Atelier — task runner.  Run `make` (or `make help`) for the grouped list.
# Override vars inline, e.g.  make start PORT=5050   /   make index PHOTOS=/Volumes/Photos
# NOTE: keep comments on their OWN line — a trailing `# ...` after `?=` joins the value.

PORT   ?= 5050           # 5000/7000 are the macOS AirPlay trap (403)
DB     ?= faces.db
PHOTOS ?=
PHOTOS_DIR   ?= ./demo_photos
PROJECTS_DIR ?= $(HOME)/.atelier
MIN_CLUSTER  ?=

PYTHON  := .venv/bin/python
PIP     := .venv/bin/pip
PIDFILE := .server.pid
LOGFILE := server.log

.DEFAULT_GOAL := help

##@ Setup
install: ## Full install: venv + pipeline deps (torch, mediapipe…) + atelier CLI
	mise install
	$(PIP) install -q -r requirements.txt -e .
	@echo "✓ installed (pipeline + CLI)"

install-dev: ## Light install: venv + test/lint deps only (no torch/mediapipe)
	mise install
	$(PIP) install -q -r requirements-dev.txt
	@echo "✓ dev deps installed"

##@ Run the app
start: ## Start the web server in the background
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
		echo "already running (pid $$(cat $(PIDFILE))) -> http://localhost:$(PORT)"; \
	else \
		$(PYTHON) -m atelier.server --projects-dir $(PROJECTS_DIR) --port $(PORT) > $(LOGFILE) 2>&1 & echo $$! > $(PIDFILE); \
		sleep 1; echo "✓ started pid $$(cat $(PIDFILE)) -> http://localhost:$(PORT)  (logs: make logs)"; \
	fi

stop: ## Stop the background web server
	@if [ -f $(PIDFILE) ]; then \
		kill $$(cat $(PIDFILE)) 2>/dev/null && echo "✓ stopped" || echo "not running"; rm -f $(PIDFILE); \
	else PIDS=$$(lsof -ti :$(PORT) 2>/dev/null); [ -n "$$PIDS" ] && kill $$PIDS && echo "✓ stopped port $(PORT)" || echo "not running"; fi

restart: stop start ## Restart the web server

status: ## Is the server running?
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
		echo "running (pid $$(cat $(PIDFILE))) -> http://localhost:$(PORT)"; else echo "stopped"; fi

open: ## Open the web UI in the browser (macOS)
	@open http://localhost:$(PORT)

logs: ## Tail the server log
	@touch $(LOGFILE); tail -f $(LOGFILE)

serve: ## Run the server in the foreground (Ctrl-C to quit)
	$(PYTHON) -m atelier.server --projects-dir $(PROJECTS_DIR) --port $(PORT)

demo: ## Seed a synthetic demo project and open it
	$(PYTHON) -m atelier.demo_seed --projects-dir $(PROJECTS_DIR) --name "Demo" --photos $(PHOTOS_DIR)
	@$(MAKE) -s start && $(MAKE) -s open

##@ Develop
test: ## Run the unit tests (no models needed)
	$(PYTHON) -m pytest -q

lint: ## Lint + format-check everything (Python always; web if Node present)
	$(PYTHON) -m ruff format --check .
	$(PYTHON) -m ruff check .
	@if command -v npx >/dev/null 2>&1; then \
		npx eslint atelier/web && npx prettier --check "atelier/web/**/*.{js,css,html}"; \
	else echo "· web lint skipped (install Node, then npm install)"; fi

format: ## Auto-format + autofix everything (Python always; web if Node present)
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .
	@if command -v npx >/dev/null 2>&1; then \
		npx eslint --fix atelier/web && npx prettier --write "atelier/web/**/*.{js,css,html}"; \
	else echo "· web format skipped (install Node, then npm install)"; fi

build: ## Build the wheel + sdist into dist/
	@rm -rf dist
	$(PYTHON) -m build
	@echo "✓ built -> dist/"

##@ Pipeline (CLI — power users; the web UI does this for you)
index: ## Phase 1 — index photos (PHOTOS=/path, resumable)
	@test -n "$(PHOTOS)" || { echo "ERROR: set PHOTOS=/path/to/photos"; exit 1; }
	$(PYTHON) -m atelier.pipeline.index --photos "$(PHOTOS)" --db $(DB)

reindex: ## Phase 1 — retry images that errored (PHOTOS=/path)
	@test -n "$(PHOTOS)" || { echo "ERROR: set PHOTOS=/path/to/photos"; exit 1; }
	$(PYTHON) -m atelier.pipeline.index --photos "$(PHOTOS)" --db $(DB) --retry-errors

cluster: ## Phase 2 — cluster faces into persons (MIN_CLUSTER=N)
	$(PYTHON) -m atelier.pipeline.cluster --db $(DB) $(if $(MIN_CLUSTER),--min-cluster-size $(MIN_CLUSTER),)

series: ## Phase 2b — group images into bursts
	$(PYTHON) -m atelier.pipeline.series --db $(DB)

score: ## Phase 3 — score quality + pick best face/frame
	$(PYTHON) -m atelier.pipeline.score --db $(DB)

pipeline: index cluster series score ## Run all 4 phases (PHOTOS=/path)
	@echo "✓ pipeline complete -> make serve"

db: ## Create an empty database (DB=faces.db)
	@$(PYTHON) -c "from atelier import db; db.init_db('$(DB)'); print('✓ created $(DB)')"

stats: ## Print row counts (DB=faces.db)
	@$(PYTHON) -c "from atelier import db; c=db.connect('$(DB)'); \
	q=lambda t: c.execute('SELECT COUNT(*) n FROM '+t).fetchone()['n']; \
	print(f\"images={q('images')} faces={q('faces')} persons={q('persons')} series={q('series')}\")"

##@ Clean up
clean: ## Remove caches, pidfile, server log
	@rm -rf atelier/__pycache__ atelier/**/__pycache__ tests/__pycache__ .pytest_cache .ruff_cache $(PIDFILE) $(LOGFILE)
	@echo "✓ cleaned"

clean-all: stop clean ## Also remove venv, node_modules, databases, demo/export folders
	@rm -rf .venv node_modules dist *.db *.db-wal *.db-shm demo_photos print_exports
	@echo "✓ wiped venv + data"

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"} \
		/^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5); next} \
		/^[a-zA-Z_-]+:.*##/ {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.PHONY: install install-dev start stop restart status open logs serve demo \
        test lint format build index reindex cluster series score pipeline db stats \
        clean clean-all help
