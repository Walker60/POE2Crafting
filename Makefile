# Dev convenience tasks. Recipes run through git-bash's bash.exe (confirmed
# via `make -f -`), so this is written as plain bash, but `start`/`stop`/
# `status` shell out to scripts/dev.ps1 for the parts that genuinely need
# real Windows process management (see that script's docstring for why).
#
# Usage: make <target>   e.g. `make install`, `make start`, `make stop`

.PHONY: help install refresh-data refresh-trade-stats start stop restart status test

help:
	@echo "poe2craft dev tasks:"
	@echo "  make install            uv sync + npm install"
	@echo "  make refresh-data       re-scrape Craft of Exile/poe2db and rebuild compiled gamedata"
	@echo "  make refresh-trade-stats  re-fetch the trade2 stat catalog + rebuild the mod->stat mapping (optional, see docs/data_provenance.md)"
	@echo "  make start              start the backend (:8000) and frontend dev server (:5173) in the background"
	@echo "  make stop               stop both"
	@echo "  make restart            stop then start"
	@echo "  make status             show what's listening on :8000/:5173"
	@echo "  make test               run the backend test suite"

install:
	uv sync
	cd frontend && npm install

refresh-data:
	uv run python scripts/refresh_all_data.py

refresh-trade-stats:
	uv run python scripts/fetch_trade_stats.py
	uv run python scripts/build_trade_stat_mapping.py

start:
	@powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 -Action start

stop:
	@powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 -Action stop

restart: stop start

status:
	@powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/dev.ps1 -Action status

test:
	uv run pytest
