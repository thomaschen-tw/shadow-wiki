# Shadow Wiki — Quick Start

Shadow Wiki watches your GitHub PRs, Slack, Linear, and local files, then uses a hybrid local/cloud LLM to keep a searchable Obsidian wiki up to date. Claude Code reads it through an MCP server.

## Prerequisites

- Python 3.12 · [uv](https://docs.astral.sh/uv/) (`brew install uv` or `pip install uv`)
- [LM Studio](https://lmstudio.ai) with a Qwen 3 model loaded **and server started**, or [Ollama](https://ollama.com) running
- (Optional) Cloud API key for new-page synthesis — Qwen Cloud, Claude, or DeepSeek

## 1. Install

```bash
git clone https://github.com/thomaschen-tw/shadow-wiki.git && cd shadow-wiki
uv sync          # creates .venv with Python 3.12 and installs all deps
```

## 2. Verify Environment

```bash
uv run python test_env.py    # checks connectivity, model name, API keys
```

Fix any `[FAIL]` items before continuing.

## 3. Configure

```bash
cp .env.example .env
```

Minimum edits in `.env`:
```env
LOCAL_LLM_BACKEND=auto          # auto-detects LM Studio or Ollama
LMSTUDIO_MODEL=qwen/qwen3-8b    # must match the model name shown in LM Studio
USE_CLOUD_LLM=false             # start local-only; enable cloud later if needed
```

## 4. Initialize

```bash
uv run python scripts/resource_mgr.py init
```

## 5. Run the Demo

```bash
bash demo.sh    # init → worker → push test diff → show wiki output
```

Or start services manually:

```bash
uv run python scripts/distill/worker.py &           # distillation worker (daemon)
uv run python scripts/ingest/github_connector.py &  # optional: GitHub webhook on :9000
```

## 6. Push Your First Entry

```bash
echo "+def login(user, pw): ..." | uv run python scripts/ingest_diff.py \
  --diff - --pr 1 --title "Add login"

# Check results (worker processes within 30s)
uv run python scripts/resource_mgr.py list
```

## 7. Connect Claude Code

Add to `~/.claude/claude.json`:

```json
{
  "mcpServers": {
    "shadow-wiki": {
      "command": "uv",
      "args": ["run", "python", "/absolute/path/to/shadow-wiki/scripts/mcp_server.py"]
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
GitHub setup guide: **[docs/github-setup.md](docs/github-setup.md)**  
Architecture diagram: **[docs/architecture.md](docs/architecture.md)**
