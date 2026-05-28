# GitHub Actions — Self-Hosted Runner Setup

Shadow Wiki uses a **self-hosted runner** so GitHub Actions jobs run on your Mac and
can access your local Obsidian vault. This is a one-time setup (~10 minutes).

---

## Why Self-Hosted?

GitHub's cloud runners cannot access files on your local machine. By installing a
small runner daemon on your Mac, GitHub Actions jobs run locally, can read
`knowledge_base/wiki/`, and can use LM Studio if it is running.

---

## Step 1 — Register the Runner on GitHub

1. Go to your repo: `https://github.com/thomaschen-tw/shadow-wiki`
2. Click **Settings → Actions → Runners → New self-hosted runner**
3. Select **macOS** and **ARM64** (Apple Silicon) or **x64** as appropriate
4. GitHub will display a set of commands — follow them in your terminal:

```bash
# Create a folder for the runner (GitHub recommends ~/actions-runner)
mkdir ~/actions-runner && cd ~/actions-runner

# Download the runner package (GitHub provides the exact URL in the UI)
curl -o actions-runner-osx-arm64.tar.gz -L <URL from GitHub UI>
tar xzf ./actions-runner-osx-arm64.tar.gz

# Configure the runner (GitHub provides the exact token in the UI)
./config.sh --url https://github.com/thomaschen-tw/shadow-wiki --token <TOKEN>
```

When asked for the runner name, labels, and work folder, press Enter to accept defaults.

---

## Step 2 — Install as a macOS Service (auto-start on login)

```bash
cd ~/actions-runner

# Install as a launchd service (starts automatically on login)
sudo ./svc.sh install
sudo ./svc.sh start

# Verify it is running
./svc.sh status
```

The runner will now appear as **Online** in GitHub → Settings → Actions → Runners.

---

## Step 3 — Verify `.env` is Configured

The runner reads `.env` from the repo root. Make sure these are set:

```env
KNOWLEDGE_BASE_PATH=/Users/xiaotongchen/Documents/obsidian/knowledge_base/wiki
KNOWLEDGE_BASE_SIMILARITY_THRESHOLD=0.85

# Cloud LLM key (used when USE_CLOUD_LLM=true in the workflow)
DASHSCOPE_API_KEY=sk-...
QWEN_CLOUD_MODEL=qwen3.6-35b-a3b
CLOUD_LLM_BACKEND=qwen_cloud
```

Run the environment checker to confirm:

```bash
uv run python test_env.py
```

---

## Step 4 — Test with a Manual Trigger

1. Go to **GitHub → Actions → Daily Knowledge Digest**
2. Click **Run workflow → Run workflow**
3. Watch the logs — each step should show green

Expected output in the "Distill notes" step:
```
Processing N pending events
INFO Created knowledge page: knowledge/concepts/rag-retrieval-augmented-generation
INFO Appended 3 insights to knowledge/comparisons/rag-vs-kag
Done
```

---

## Step 5 — Verify Wiki Output

After the job completes, check your repo on GitHub:

```
wiki/knowledge/
├── concepts/
│   ├── rag-retrieval-augmented-generation.md
│   ├── multi-agent-systems.md
│   └── skillsops.md
├── comparisons/
│   └── rag-vs-kag.md
├── entities/
│   └── obsidian.md
└── summaries/
    └── agentic-ai-guide-summary.md
```

Each page will have sections: **Overview**, **Key Concepts**, **Key Insights**,
**Sources**, **Related Topics**.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Runner shows **Offline** in GitHub | Run `./svc.sh start` in `~/actions-runner` |
| `uv: command not found` | Add uv to PATH: `export PATH="$HOME/.cargo/bin:$PATH"` in `~/.zshrc` |
| `KNOWLEDGE_BASE_PATH does not exist` | Check the path in `.env` matches your actual vault location |
| `No pending events` | Run `--force` once: `uv run python scripts/ingest/knowledge_base_scanner.py --force --once` |
| LLM timeout | Increase `LLM_TIMEOUT=600` in `.env`, or check cloud API key |
| `git push` fails | Ensure runner has push permissions: Settings → Actions → Workflow permissions → Read and write |

---

## Stopping / Uninstalling the Runner

```bash
cd ~/actions-runner
sudo ./svc.sh stop
sudo ./svc.sh uninstall

# Remove from GitHub: Settings → Actions → Runners → click runner → Remove
```
