# 🤖 YogiBot — Personal AI Assistant

A fully layered, self-hostable AI assistant accessible via **Telegram**, powered by **Claude (Anthropic)**, with deep tool integration via **MCP (Model Context Protocol)**.

Inspired by MolBot / ClawBot, redesigned with a Layered Context Engine architecture.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Layer-by-Layer Design](#layer-by-layer-design)
3. [MCP Servers](#mcp-servers)
4. [Quick Start](#quick-start)
5. [Configuration](#configuration)
6. [Skills System](#skills-system)
7. [Memory System](#memory-system)
8. [RAG Knowledge Base](#rag-knowledge-base)
9. [File Reference](#file-reference)
10. [Running Tests](#running-tests)
11. [Docker Deployment](#docker-deployment)
12. [Troubleshooting](#troubleshooting)

---

## Architecture Overview

YogiBot uses a **Layered Context Engine** — a deliberate pipeline that processes every message through four layers before the LLM sees it. This eliminates wasted compute on simple messages and ensures every complex request has the right context injected.

```
┌──────────────────────────────────────────────────────────┐
│                  TELEGRAM INTERFACE                      │
│         telegram_handler/handler.py                      │
│   Security gate → command routing → message dispatch     │
└──────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│              CORE ASSISTANT ENGINE                       │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │  1. Intent Classification Layer                  │    │
│  │     engine/intent_classifier.py                  │    │
│  │     Tags each message: CHAT / QUERY / ACTION / SKILL  │
│  └──────────────────────────────────────────────────┘    │
│                           │                              │
│                           ▼                              │
│  ┌──────────────────────────────────────────────────┐    │
│  │  2. Request Router & Orchestrator                │    │
│  │     engine/router.py                             │    │
│  │     Assembles context window, calls LLM          │    │
│  └──────────────────────────────────────────────────┘    │
│                           │                              │
│          ┌────────────────┼────────────────┐             │
│          ▼                ▼                ▼             │
│  ┌──────────────┐ ┌──────────────┐ ┌─────────────┐      │
│  │  3a. Skill   │ │  3b. MCP     │ │  3c. RAG    │      │
│  │  Executor    │ │  Coordinator │ │  Pipeline   │      │
│  └──────────────┘ └──────────────┘ └─────────────┘      │
└──────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│                     MCP LAYER                            │
│  Telegram MCP │ GitHub MCP │ Windows MCP │ Filesystem MCP│
│               │ LinkedIn MCP                             │
└──────────────────────────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────┐
│               KNOWLEDGE & DATA LAYER                     │
│  ChromaDB (RAG) │ Skill Registry (.yaml) │ Memory Store  │
└──────────────────────────────────────────────────────────┘
```

---

## Layer-by-Layer Design

### Layer 1: Intent Classifier (`engine/intent_classifier.py`)

Every incoming message is tagged with one of four intents **before anything expensive runs**. This is the key optimization over v1 — simple messages like "thanks!" never touch RAG or tools.

| Intent | Description | Examples |
|--------|-------------|---------|
| `CHAT` | Pure conversation, no tools | "good morning!", "thanks!", "lol" |
| `QUERY` | Factual question → run RAG | "what did we decide last week?" |
| `ACTION` | Requires MCP tool execution | "create a GitHub issue for bug X" |
| `SKILL` | Named skill matched by trigger | "summarize this channel" |

**Two modes** (set `INTENT_MODE` in `.env`):
- `rule` (default) — regex patterns, fast, free, deterministic, ~0ms
- `llm` — claude-haiku classification, ~200ms, costs tokens, more accurate

### Layer 2: Request Router (`engine/router.py`)

Takes the classified intent and:
1. **Always** loads memory context (SOUL.md, USER.md, MEMORY.md, today's log)
2. **Conditionally** triggers RAG (only for `QUERY`)
3. **Conditionally** loads tools (only for `ACTION` and `SKILL`)
4. Assembles the complete context window
5. Calls the Anthropic API (with or without tools)
6. Saves the turn to memory and daily log

**Context window structure:**
```
SYSTEM PROMPT
  └── SOUL.md             (persona — always)
  └── USER.md             (user prefs — always)
  └── TOOLS.md            (env notes — always)
  └── MEMORY.md           (curated facts — always)
  └── Today's daily log   (recency — always)
  └── Tool names          (only if ACTION or SKILL)
─────────────────────────
CONVERSATION HISTORY      (last 20 turns — always)
─────────────────────────
RAG CONTEXT               (only if QUERY intent)
─────────────────────────
USER MESSAGE              (always)
```

### Layer 3a: Skill Executor (`skills/executor.py`)

Loads named skills from `skills/registry/*.yaml`. Each skill has:
- `name` — unique identifier
- `description` — shown in `/skills` command
- `triggers` — regex patterns for the intent classifier
- `prompt_template` — Jinja2-style template with `{{message}}`
- `tools` — list of MCP tool names the skill needs

**Default skills included:**
- `summarize` — Summarize conversations/documents
- `scan_bugs` — Code review and bug finding
- `draft_message` — Professional message drafting
- `github_workflow` — GitHub issue/PR management
- `telegram_manage` — Telegram chat management
- `file_manager` — Filesystem operations

**Adding a custom skill:** create `skills/registry/my_skill.yaml`:
```yaml
name: my_skill
description: Does my custom thing
version: "1.0"
tags: [custom]
triggers:
  - '\bmy\s+skill\b'
  - '\bcustom\s+task\b'
tools: []
prompt_template: |
  Perform this custom task:
  {{message}}
```

### Layer 3b: MCP Coordinator (`mcp/coordinator.py`)

Manages all MCP server connections and routes tool calls. Provides Anthropic-format tool definitions to the Router for the agentic tool-use loop.

Each MCP server is enabled only if its credentials are present in `.env`.

### Layer 3c: RAG Pipeline (`rag/retriever.py`)

Uses **ChromaDB** (local vector database) and **sentence-transformers** for semantic search.

- Splits documents into overlapping chunks (512 chars, 64 overlap)
- Embeds with `all-MiniLM-L6-v2` (lightweight, runs on CPU)
- Retrieves top-5 most relevant chunks for QUERY intents
- Automatically indexes all files in `data/memory/` and `data/daily_logs/`

---

## MCP Servers

YogiBot integrates 5 MCP servers. Each is enabled only when credentials are configured.

### 1. Telegram MCP
**Source:** [chigwell/telegram-mcp](https://github.com/chigwell/telegram-mcp)  
**What it does:** Lets the bot interact with your **personal Telegram account** (not just bot-to-user). Powered by Telethon.

**Tools available:**
- `telegram_send_message` — Send a message to any chat
- `telegram_get_messages` — Read messages from a chat
- `telegram_list_chats` — List all your chats
- `telegram_search_messages` — Search messages in a chat
- `telegram_create_group` — Create a new group

**Setup:**
1. Get API credentials at [my.telegram.org/apps](https://my.telegram.org/apps)
2. Generate session string: `python scripts/gen_telegram_session.py`
3. Add to `.env`: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING`

> ⚠️ **Security:** The session string gives full access to your Telegram account. Never commit it to git.

---

### 2. GitHub MCP
**Source:** [github/github-mcp-server](https://github.com/github/github-mcp-server)  
**What it does:** Full GitHub integration — create issues, PRs, search code, read files.

**Tools available:**
- `github_create_issue` — Create an issue in any repo
- `github_list_issues` — List open/closed issues
- `github_create_pull_request` — Open a PR
- `github_search_code` — Search code across GitHub
- `github_get_file` — Read a file from any repo

**Setup:**
1. Create a GitHub Personal Access Token at [github.com/settings/tokens](https://github.com/settings/tokens)
2. Grant: `repo`, `issues`, `pull_requests`, `read:org`
3. Add to `.env`: `GITHUB_TOKEN=ghp_xxx...`

---

### 3. Windows MCP
**Source:** [CursorTouch/Windows-MCP](https://github.com/CursorTouch/Windows-MCP)  
**What it does:** Computer use on Windows — take screenshots, click, type, open apps, run commands.

**Tools available:**
- `windows_screenshot` — Capture the screen
- `windows_type_text` — Type via keyboard
- `windows_click` — Click at coordinates
- `windows_open_app` — Launch applications
- `windows_run_command` — Run PowerShell/CMD commands

**Setup:** Automatically enabled on Windows. Requires `pyautogui`:
```bash
pip install pyautogui
```

> ℹ️ This server is a no-op on macOS/Linux.

---

### 4. Filesystem MCP
**Source:** [modelcontextprotocol/servers/filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem)  
**What it does:** Read, write, search, and manage local files.

**Tools available:**
- `fs_read_file` — Read file contents
- `fs_write_file` — Write/create a file
- `fs_list_directory` — List directory contents
- `fs_search_files` — Glob search for files
- `fs_delete_file` — Delete a file

**Setup:** Always enabled. No credentials needed.

---

### 5. LinkedIn MCP
**Source:** [stickerdaniel/linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server)  
**What it does:** LinkedIn profile lookup, job search, and posting.

**Tools available:**
- `linkedin_get_profile` — Get a profile's info
- `linkedin_search_jobs` — Search job listings
- `linkedin_create_post` — Post to LinkedIn

**Setup:**
1. Add to `.env`: `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD`
2. Install: `pip install linkedin-mcp-server`

---

## Quick Start

### Prerequisites
- Python 3.11+
- A Telegram account + Bot token (from [@BotFather](https://t.me/BotFather))
- An Anthropic API key

### 1. Clone and configure

```bash
git clone <your-repo>
cd yogibot
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Telegram Bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow prompts
3. Copy the token to `.env` as `TELEGRAM_BOT_TOKEN`

### 4. Run

```bash
python main.py
```

### 5. Chat with your bot

Open Telegram and send a message to your bot. Try:
- `/start` — welcome message
- `/help` — show all commands
- `/skills` — list available skills
- `/status` — check MCP connections
- "What did we discuss yesterday?" — QUERY
- "Create a GitHub issue for bug X" — ACTION
- "summarize this" — SKILL
- "good morning!" — CHAT

---

## Configuration

All configuration is in `.env`. Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | Anthropic API key | required |
| `ANTHROPIC_MODEL` | Main Claude model | `claude-sonnet-4-20250514` |
| `ANTHROPIC_HAIKU_MODEL` | Fast model for intent | `claude-haiku-4-5-20251001` |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | required |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated user IDs (empty = allow all) | |
| `INTENT_MODE` | `rule` or `llm` | `rule` |
| `RAG_TOP_K` | Max RAG results per query | `5` |
| `RAG_MIN_SCORE` | Minimum similarity score (0-1) | `0.3` |
| `MAX_CONVERSATION_HISTORY` | Turns to include in context | `20` |
| `EMBEDDING_MODEL` | Sentence transformer model | `all-MiniLM-L6-v2` |

---

## Memory System

YogiBot has four memory layers:

| File | Scope | Description |
|------|-------|-------------|
| `SOUL.md` | Global | Bot persona — who it is, how it behaves |
| `TOOLS.md` | Global | Environment notes — what tools are available |
| `USER_{id}.md` | Per-user | User preferences and context |
| `MEMORY_{id}.md` | Per-user | Curated facts the bot has learned |
| `history_{id}.jsonl` | Per-user | Full conversation history |
| `daily_logs/YYYY-MM-DD.md` | Global | All interactions logged by day |

**Customizing SOUL.md:** Edit `data/memory/SOUL.md` to change the bot's persona.

**Adding memory facts via bot:**
The bot automatically saves important information. You can also directly edit `data/memory/MEMORY_{your_user_id}.md`.

---

## RAG Knowledge Base

The RAG system lets YogiBot search through all your documents semantically.

**What gets auto-indexed:**
- All files in `data/memory/`
- Last 30 days of daily logs

**Indexing custom documents:**
```bash
# Index a single file
python scripts/index_docs.py --file /path/to/doc.md

# Index a whole directory
python scripts/index_docs.py --dir /path/to/docs/

# Check stats
python scripts/index_docs.py --stats

# Clear and re-index everything
python scripts/index_docs.py --clear --dir data/memory/
```

**Via Telegram:**
Send `/index` to re-index all memory files.

---

## File Reference

```
yogibot/
├── main.py                          # Entry point
├── requirements.txt                 # Python dependencies
├── .env.example                     # Config template
├── Dockerfile                       # Docker build
├── docker-compose.yml               # Docker Compose
│
├── config/
│   ├── __init__.py
│   └── settings.py                  # Settings loader (from .env)
│
├── telegram_handler/
│   ├── __init__.py
│   └── handler.py                   # Telegram bot handler, security gate, commands
│
├── engine/
│   ├── __init__.py
│   ├── intent_classifier.py         # Layer 1: message intent tagging
│   └── router.py                    # Layer 2: context assembly + LLM orchestration
│
├── memory_store/
│   ├── __init__.py
│   └── memory.py                    # SOUL/USER/MEMORY/history management
│
├── rag/
│   ├── __init__.py
│   └── retriever.py                 # ChromaDB indexing + semantic search
│
├── mcp/
│   ├── __init__.py
│   ├── coordinator.py               # MCP server management + tool routing
│   └── mcp_config_reference.json   # Config reference for external MCP clients
│
├── skills/
│   ├── __init__.py
│   ├── executor.py                  # Skill loading + execution
│   └── registry/                   # Skill YAML definitions
│       ├── summarize.yaml
│       ├── scan_bugs.yaml
│       ├── draft_message.yaml
│       ├── github_workflow.yaml
│       ├── telegram_manage.yaml
│       └── file_manager.yaml
│
├── data/
│   ├── memory/                      # SOUL.md, MEMORY_*.md, USER_*.md, history_*.jsonl
│   ├── chroma_db/                   # ChromaDB vector store (auto-created)
│   ├── daily_logs/                  # YYYY-MM-DD.md conversation logs
│   └── logs/                        # Application logs
│
├── scripts/
│   └── index_docs.py                # Manual RAG indexer
│
└── tests/
    └── test_all.py                  # Test suite
```

---

## Running Tests

```bash
python tests/test_all.py
```

Tests cover:
1. **Architecture** — all modules import correctly
2. **Intent Classifier** — 10 test cases, rule-based and LLM mode
3. **Memory Store** — SOUL, prefs, facts, history, persistence
4. **RAG Retriever** — indexing, semantic search, chunking
5. **Skill Executor** — YAML loading, trigger matching, prompt rendering
6. **MCP Coordinator** — server status, tool listing, filesystem execution

---

## Docker Deployment

```bash
# Build and run
docker compose up --build -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

Data is persisted in `./data/` via volume mount.

---

## Troubleshooting

**Bot not responding:**
- Check `TELEGRAM_BOT_TOKEN` is correct
- Check `ANTHROPIC_API_KEY` is valid
- Check `data/logs/yogibot.log` for errors

**MCP server not connecting:**
- Run `/status` in Telegram to see which servers are enabled
- Make sure all credentials for that server are in `.env`
- Telegram MCP: regenerate session string if you see auth errors

**RAG not returning results:**
- Run `python scripts/index_docs.py --stats` to check chunk count
- If 0 chunks: run `python scripts/index_docs.py --dir data/memory/`
- Lower `RAG_MIN_SCORE` in `.env` (try `0.1`)

**Intent misclassification:**
- Switch to `INTENT_MODE=llm` for better accuracy
- Or add custom patterns to `engine/intent_classifier.py`

**Out of context / wrong memory:**
- Run `/clear` to reset conversation history
- Check `data/memory/MEMORY_{your_id}.md` for stale facts

---

## Security Notes

- Never commit `.env` to git — it's in `.gitignore`
- The Telegram session string gives full access to your account
- Set `TELEGRAM_ALLOWED_USERS` to restrict bot access to your user ID only
- Find your Telegram user ID: message [@userinfobot](https://t.me/userinfobot)
