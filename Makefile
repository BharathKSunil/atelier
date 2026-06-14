# Photo Face Indexer — task runner
# Override vars inline, e.g.:  make index PHOTOS=/Volumes/Photos
#                             make start DB=faces.db PORT=5050

DB     ?= faces.db
PORT   ?= 5050   # avoid 5000/7000 — macOS AirPlay Receiver binds those (returns 403)
PHOTOS ?=
PHOTOS_DIR ?= ./demo_photos
PROJECTS_DIR ?= $(HOME)/.atelier   # project storage root (override with ATELIER_HOME too)

PYTHON := .venv/bin/python
PIP    := .venv/bin/pip
PIDFILE := .server.pid
LOGFILE := server.log

.DEFAULT_GOAL := help

# ---------------------------------------------------------------- setup
.PHONY: install
install: ## Create venv (mise) + install full pipeline deps (torch, mediapipe, ...)
	mise install
	$(PIP) install -q -r requirements.txt
	@echo "✓ pipeline deps installed"

.PHONY: install-dev
install-dev: ## Create venv (mise) + install light test deps only
	mise install
	$(PIP) install -q -r requirements-dev.txt
	@echo "✓ dev deps installed"

.PHONY: test
test: ## Run pure-logic unit tests (no models needed)
	$(PYTHON) -m pytest -q

.PHONY: check
check: ## Byte-compile every script (fast syntax check)
	$(PYTHON) -m py_compile *.py facelib/*.py && echo "✓ all compile"

# ---------------------------------------------------------------- database
.PHONY: db
db: ## Create an empty database (DB=faces.db)
	@$(PYTHON) -c "from facelib import db; db.init_db('$(DB)'); print('✓ created $(DB)')"

.PHONY: db-reset
db-reset: ## Delete and recreate the database (DB=faces.db)
	@rm -f $(DB) $(DB)-wal $(DB)-shm
	@$(MAKE) -s db DB=$(DB)

.PHONY: stats
stats: ## Print row counts in the database (DB=faces.db)
	@$(PYTHON) -c "from facelib import db; c=db.connect('$(DB)'); \
	q=lambda t: c.execute('SELECT COUNT(*) n FROM '+t).fetchone()['n']; \
	print(f\"images={q('images')} faces={q('faces')} persons={q('persons')} series={q('series')}\")"

# ---------------------------------------------------------------- pipeline
.PHONY: index
index: ## Phase 1 — index photos (requires PHOTOS=/path, resumable)
	@test -n "$(PHOTOS)" || { echo "ERROR: set PHOTOS=/path/to/photos"; exit 1; }
	$(PYTHON) 01_index.py --photos "$(PHOTOS)" --db $(DB)

.PHONY: reindex
reindex: ## Phase 1 — retry images that errored last run (PHOTOS=/path)
	@test -n "$(PHOTOS)" || { echo "ERROR: set PHOTOS=/path/to/photos"; exit 1; }
	$(PYTHON) 01_index.py --photos "$(PHOTOS)" --db $(DB) --retry-errors

MIN_CLUSTER ?=
.PHONY: cluster
cluster: ## Phase 2 — cluster faces into persons (MIN_CLUSTER=N to override)
	$(PYTHON) 02_cluster_persons.py --db $(DB) $(if $(MIN_CLUSTER),--min-cluster-size $(MIN_CLUSTER),)

.PHONY: series
series: ## Phase 2b — group images into series/bursts
	$(PYTHON) 02b_group_series.py --db $(DB)

.PHONY: score
score: ## Phase 3 — score quality, pick best face + best print frame
	$(PYTHON) 03_score.py --db $(DB)

.PHONY: pipeline
pipeline: index cluster series score ## Run all 4 phases (requires PHOTOS=/path)
	@echo "✓ pipeline complete -> make serve DB=$(DB)"

# ---------------------------------------------------------------- server
.PHONY: start
start: ## Start web server in background (PROJECTS_DIR=, PORT=)
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
		echo "already running (pid $$(cat $(PIDFILE))) on http://localhost:$(PORT)"; \
	else \
		$(PYTHON) 04_server.py --projects-dir $(PROJECTS_DIR) --port $(PORT) > $(LOGFILE) 2>&1 & echo $$! > $(PIDFILE); \
		sleep 1; echo "✓ started pid $$(cat $(PIDFILE)) -> http://localhost:$(PORT)  (logs: make logs)"; \
	fi

.PHONY: stop
stop: ## Stop the background web server
	@if [ -f $(PIDFILE) ]; then \
		kill $$(cat $(PIDFILE)) 2>/dev/null && echo "✓ stopped pid $$(cat $(PIDFILE))" || echo "not running"; \
		rm -f $(PIDFILE); \
	else \
		PIDS=$$(lsof -ti :$(PORT) 2>/dev/null); \
		[ -n "$$PIDS" ] && kill $$PIDS && echo "✓ stopped port $(PORT)" || echo "not running"; \
	fi

.PHONY: restart
restart: stop start ## Restart the web server

.PHONY: serve
serve: ## Run web server in the foreground (Ctrl-C to quit)
	$(PYTHON) 04_server.py --projects-dir $(PROJECTS_DIR) --port $(PORT)

.PHONY: status
status: ## Show whether the server is running
	@if [ -f $(PIDFILE) ] && kill -0 $$(cat $(PIDFILE)) 2>/dev/null; then \
		echo "running (pid $$(cat $(PIDFILE))) -> http://localhost:$(PORT)"; \
	else echo "stopped"; fi

.PHONY: logs
logs: ## Tail the server log
	@touch $(LOGFILE); tail -f $(LOGFILE)

.PHONY: open
open: ## Open the web UI in the browser
	@open http://localhost:$(PORT)

# ---------------------------------------------------------------- demo
.PHONY: seed
seed: ## Build the synthetic demo database (demo.db + demo_photos/)
	$(PYTHON) demo_seed.py --db demo.db --photos $(PHOTOS_DIR)

.PHONY: demo
demo: ## Seed a demo project and open the dashboard
	$(PYTHON) demo_seed.py --projects-dir $(PROJECTS_DIR) --name "Demo" --photos $(PHOTOS_DIR)
	@$(MAKE) -s start
	@$(MAKE) -s open

# ---------------------------------------------------------------- cleanup
.PHONY: clean
clean: ## Remove caches, pidfile, server log
	@rm -rf __pycache__ facelib/__pycache__ tests/__pycache__ .pytest_cache $(PIDFILE) $(LOGFILE)
	@echo "✓ cleaned"

.PHONY: clean-all
clean-all: stop clean ## Also remove venv, databases, demo + export folders
	@rm -rf .venv *.db *.db-wal *.db-shm demo_photos print_exports
	@echo "✓ wiped venv + data"

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
