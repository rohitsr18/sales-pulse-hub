.PHONY: install install-dev test lint format type-check validate clean

# ── Setup ────────────────────────────────────────────────────────────────
install:
	pip install -e "sim/[dev]"
	pip install -e "starter/[dev]"

install-dev: install

# ── Quality gates ────────────────────────────────────────────────────────
lint:
	ruff check sim/ starter/

lint-fix:
	ruff check --fix sim/ starter/

format:
	black sim/ starter/

format-check:
	black --check sim/ starter/

type-check:
	mypy sim/sim starter/hub

test:
	cd sim     && pytest --tb=short -q
	cd starter && pytest --tb=short -q

test-cov:
	cd sim     && pytest --cov=sim     --cov-report=term-missing
	cd starter && pytest --cov=hub     --cov-report=term-missing

validate: lint format-check type-check test

# ── Run ─────────────────────────────────────────────────────────────────
sim:
	cd sim && python server.py

hub:
	cd starter && python server.py

dev:
	# Requires the 'concurrently' shim or run in two terminals
	python -m concurrently "make sim" "make hub"

# ── Docker ───────────────────────────────────────────────────────────────
docker-build:
	docker build -t salespulse-sim:latest ./sim
	docker build -t salespulse-hub:latest ./starter

docker-up:
	docker compose up --build

docker-down:
	docker compose down

# ── Housekeeping ─────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__   -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache   -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info"  -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc"               -delete               2>/dev/null || true
