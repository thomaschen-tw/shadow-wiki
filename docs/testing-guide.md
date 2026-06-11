# PulseWiki Local Testing Guide (v1.3)

This guide is for first-time contributors who want to validate PulseWiki locally from zero to confidence.

**Timezone Context:** All timestamps use Asia/Shanghai (CST, UTC+8). Timestamps in test output, wiki files, and database records will reflect this timezone.

## 1. Prerequisites

1. Python 3.12
2. `uv` installed
3. `.env` configured
4. Local LLM running (LM Studio or Ollama)

**Timezone Verification:**
```bash
date  # Should show TZ=Asia/Shanghai or equivalent
# If not, run: export TZ=Asia/Shanghai && date
```

Quick setup:

```bash
uv sync
cp .env.example .env
uv run python test_env.py
```

## 2. Understand The Three Testing Layers

1. Environment checks: confirms runtime, secrets, and model connectivity.
2. Pipeline smoke tests: validates ETL loop and wiki write path with dry-run/apply.
3. Regression tests: validates unit/integration behavior with pytest.

## 3. Environment Checks (Always Run First)

```bash
uv run python test_env.py
uv run python scripts/resource_mgr.py init
uv run python scripts/resource_mgr.py status
uv run python scripts/resource_mgr.py paths
```

Expected:
1. No fatal errors from `test_env.py`.
2. DB initializes successfully.
3. `paths` shows intended write target and resolved directory.

## 4. ETL Smoke Testing (Recommended Path)

### 4.1 Dry-run cycle (safe)

```bash
uv run python scripts/resource_mgr.py etl-status
uv run python scripts/resource_mgr.py etl-run all --limit 20
uv run python scripts/resource_mgr.py etl-status
```

What to check:
1. `cleaned/routed/distilled` counts move.
2. No unexpected failures in staging.
3. No file writes in dry-run mode.

### 4.2 Apply cycle (writes enabled)

```bash
uv run python scripts/resource_mgr.py etl-run all --apply --limit 20
uv run python scripts/resource_mgr.py etl-status
uv run python scripts/resource_mgr.py list
```

What to check:
1. Modules are created/updated in the active write target.
2. Staging shows completed rows.

### 4.3 Adaptive loop test

```bash
uv run python scripts/resource_mgr.py etl-loop --limit 50 --base-sleep 30
# stop with Ctrl+C after observing 2-3 cycles
```

Observe:
1. Loop prints cycle summaries.
2. Backpressure/degraded logs appear only when inflight/recent_failed thresholds trigger.

## 5. Replay And Recovery Test

Use replay to validate recoverability on a time window.

```bash
uv run python scripts/resource_mgr.py etl-replay \
  --since "2026-06-08 00:00:00" \
  --until "2026-06-08 23:59:59" \
  --limit 200

uv run python scripts/resource_mgr.py etl-replay \
  --since "2026-06-08 00:00:00" \
  --until "2026-06-08 23:59:59" \
  --apply --limit 200
```

## 6. Staging Retention Test

```bash
# dry-run retention
uv run python scripts/resource_mgr.py etl-archive --hours 24

# apply retention
uv run python scripts/resource_mgr.py etl-archive --hours 24 --apply

# optional hard prune (careful)
uv run python scripts/resource_mgr.py etl-prune --hours 168 --mode prune
```

## 7. Pytest Regression Commands

### 7.1 Fast confidence path

```bash
uv run pytest -q -m p0 --maxfail=1
```

### 7.2 ETL critical subset (current 25 cases)

```bash
uv run pytest -q tests/test_db.py tests/test_worker.py tests/test_integration.py
```

### 7.3 Full regression triage (recommended before push)

```bash
uv run python scripts/qa/full_regression_triage.py
```

Artifacts are generated under `artifacts/regression/` for local analysis.

## 8. Typical Day-1 Testing Checklist

1. `uv run python test_env.py`
2. `uv run python scripts/resource_mgr.py init`
3. Dry-run ETL once
4. Apply ETL once
5. Run `pytest -m p0`
6. Run full triage script

If all six pass, your local environment is ready for feature testing.

## 9. Troubleshooting Quick Map

1. `sqlite3.OperationalError` about schema columns
- Run `uv run python scripts/resource_mgr.py init` again to apply migrations.

2. LLM/model connection failure
- Check `.env` model id and backend; run `uv run python scripts/resource_mgr.py llm`.

3. ETL loop appears idle
- Check `status` pending count and verify connectors are sending events.

4. Unexpected writes to wrong directory
- Check `resource_mgr.py paths` and confirm `WIKI_WRITE_TARGET`.
