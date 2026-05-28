# Shadow Wiki — Quick Start

Shadow Wiki watches your GitHub PRs, Slack, Linear, and local files, then uses a hybrid local/cloud LLM to keep a searchable Obsidian wiki up to date. Claude Code reads it through an MCP server.

## Prerequisites

- Python 3.11+
- [LM Studio](https://lmstudio.ai) with **Qwen3-35B** loaded and server running on `http://localhost:1234`
- (Optional) Claude / Qwen Cloud / DeepSeek API key for wiki-creation tasks

## 1. Install

```bash
git clone <repo-url> shadow-wiki && cd shadow-wiki
uv sync          # creates .venv with Python 3.12 and installs all deps
```

## 2. Configure

```bash
cp .env.example .env
# Required: set ANTHROPIC_API_KEY (or switch CLOUD_LLM_BACKEND to deepseek/qwen_cloud)
# Optional: GITHUB_TOKEN, SLACK_BOT_TOKEN, SLACK_APP_TOKEN, LINEAR_API_KEY
```

Default routing — no changes needed for local-only use:
```env
LOCAL_LLM_BACKEND=lmstudio   # classify / summarize / append
CLOUD_LLM_BACKEND=claude     # create new wiki pages
```

## 3. Initialize

```bash
uv run python scripts/resource_mgr.py init
```

## 4. Start Services

```bash
uv run python scripts/distill/worker.py &           # distillation worker
uv run python scripts/ingest/github_connector.py &  # GitHub webhook on :9000 (if using GitHub)
uv run python scripts/mcp_server.py                 # MCP server (keep in foreground or run via Claude Code)
```

## 5. Push Your First Entry

```bash
echo "+def login(user, pw): ..." | uv run python scripts/ingest_diff.py \
  --diff - --pr 1 --title "Add login"

# The worker processes it; check results:
uv run python scripts/resource_mgr.py list
```

## 6. Connect Claude Code

Add to `~/.claude/claude.json`:

```json
{
  "mcpServers": {
    "shadow-wiki": {
      "command": "python",
      "args": ["/absolute/path/to/shadow-wiki/scripts/mcp_server.py"]
    }
  }
}
```

Then in Claude Code:

```
search_wiki("login authentication")
get_module("auth/session")
```

---

Full documentation: **[docs/SOP.md](docs/SOP.md)**
