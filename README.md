# 🤖 LocalMind — Local AI Personal Assistant with Agentic Capabilities

A fully self-hostable **local** AI personal assistant accessible via **Telegram**, powered by a **local LLM backend (Ollama)** through an OpenAI-compatible API, with deep tool integration via **MCP (Model Context Protocol)**. Because the model runs locally, your data never has to leave your machine.

LocalMind is built around an **LLM-first, agentic architecture**. There are no hand-written routing rules deciding what to do — every message flows through a **Plan → Execute → Respond** loop, and the model itself decides which memory, knowledge, skills, and tools to use.

---

## Table of Contents

1. [Key Features](#key-features)
2. [High-Level Architecture](#high-level-architecture)
3. [Low-Level Architecture (Plan → Execute → Respond)](#low-level-architecture-plan--execute--respond)
4. [Component Design](#component-design)
5. [File Structure](#file-structure)
6. [MCP Servers](#mcp-servers)
7. [Quick Start](#quick-start)
8. [Configuration](#configuration)
9. [Skills System](#skills-system)
10. [Memory System](#memory-system)
11. [RAG Knowledge Base](#rag-knowledge-base)
12. [Running Tests](#running-tests)
13. [Docker Deployment](#docker-deployment)
14. [Troubleshooting](#troubleshooting)
15. [Security Notes](#security-notes)

---

## Key Features

- 🧠 **LLM-first agentic loop** — the model plans, calls tools in a loop, then writes a clean answer.
- 🔒 **100% local LLM** — runs on Ollama; no cloud API keys needed for the brain.
- 🔧 **MCP tool integration** — Telegram, GitHub, Filesystem, Windows, and LinkedIn, all discovered dynamically.
- 📚 **RAG knowledge base** — semantic search over your notes and daily logs (ChromaDB + sentence-transformers).
- 💾 **Layered memory** — persona, per-user facts, preferences, conversation history, and daily logs.
- 🎯 **Skills** — reusable YAML prompt skills and Python handler skills (e.g. the meeting assistant).
- 📱 **Telegram interface** — with a security whitelist and slash commands.

---

## High-Level Architecture

At the highest level, LocalMind is four cooperating layers. A message enters through Telegram, the **Engine** drives the agentic loop, the **Capability layer** exposes everything the model can do as a single flat tool list, and the **Data layer** persists knowledge and memory.

```
┌──────────────────────────────────────────────────────────────────┐
│                        USER (Telegram app)                         │
└──────────────────────────────────────────────────────────────────┘
                                  │  text message
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│  1. INTERFACE LAYER            telegram_handler/handler.py         │
│     • Security gate (allowed-users whitelist)                       │
│     • Slash commands: /start /help /memory /skills /clear /status   │
│     • Dispatches plain messages to the Engine                      │
└──────────────────────────────────────────────────────────────────┘
                                  │  process(user, message)
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│  2. ENGINE LAYER               engine/router.py                    │
│     LLM-first orchestrator — runs the agentic loop:                │
│                                                                    │
│        ┌──────────┐     ┌───────────┐     ┌────────────┐          │
│        │  PLAN    │ ──► │  EXECUTE  │ ──► │  RESPOND   │          │
│        └──────────┘     └───────────┘     └────────────┘          │
│                              │  (tool calls)                        │
└──────────────────────────────┼─────────────────────────────────────┘
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│  3. CAPABILITY LAYER           skills/tool_registry.py             │
│     One flat tool list handed to the LLM. The model picks tools.   │
│                                                                    │
│   ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌──────────────────┐  │
│   │  Memory   │ │   RAG     │ │  Skills   │ │  MCP Coordinator │  │
│   │  tools    │ │  search   │ │ executor  │ │  (mcp/…)         │  │
│   └───────────┘ └───────────┘ └───────────┘ └──────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│  4. DATA / EXTERNAL LAYER                                          │
│   ChromaDB (vectors) │ Memory files (.md/.jsonl) │ Daily logs      │
│   MCP servers: Telegram · GitHub · Filesystem · Windows · LinkedIn │
│   Local LLM: Ollama (OpenAI-compatible /chat/completions)          │
└──────────────────────────────────────────────────────────────────┘
```

---

## Low-Level Architecture (Plan → Execute → Respond)

Every message is handled by three LLM stages in `engine/router.py`. **There is no intent classifier in the active path** — the model decides everything. (`engine/intent_classifier.py` is kept only as a legacy/optional component.)

```
                 user message  +  SOUL.md persona  +  tool list
                                     │
        ══════════════════════════════════════════════════════════
        STAGE 1 — PLAN                              _plan()
        ──────────────────────────────────────────────────────────
        • LLM reads the message and the names of all tools.
        • Produces a short step-by-step plan (max ~5 steps).
        • No tools are called yet. Temperature 0.3.
        Output:  "PLAN: 1. … 2. …"
        ══════════════════════════════════════════════════════════
                                     │  plan
                                     ▼
        ══════════════════════════════════════════════════════════
        STAGE 2 — EXECUTE                           _execute()
        ──────────────────────────────────────────────────────────
        Agentic tool loop (up to 15 iterations):
                                                                    
          ┌─────────────────────────────────────────────────┐     
          │  call LLM with full tool schemas (tool_choice=   │     
          │  auto)                                           │     
          └─────────────────────────────────────────────────┘     
                     │                         ▲                    
          finish = "tool_calls"?               │ tool results       
                     │ yes                      │ appended           
                     ▼                         │                    
          ┌─────────────────────────────────────────────────┐     
          │  ToolRegistry.execute(name, args)               │     
          │    • memory_*          → MemoryStore            │     
          │    • knowledge_search  → RAGRetriever           │     
          │    • skill_<name>      → SkillExecutor          │     
          │    • <server>__<tool>  → MCPCoordinator         │     
          └─────────────────────────────────────────────────┘     
                     │ no more tool calls                           
                     ▼                                              
          collect execution_log  ─────────────────────────►        
        ══════════════════════════════════════════════════════════
                                     │  execution results
                                     ▼
        ══════════════════════════════════════════════════════════
        STAGE 3 — RESPOND                           _respond()
        ──────────────────────────────────────────────────────────
        • LLM reflects on the plan + all tool results.
        • Writes the final, natural-language reply. Temperature 0.7.
        • Never leaks raw tool output or "stage" wording.
        ══════════════════════════════════════════════════════════
                                     │  final reply
                                     ▼
        save turn → MemoryStore (history_*.jsonl) + daily log
                                     │
                                     ▼
                          Telegram reply to user
```

**Why this design?** The model sees the whole toolbox and its own plan, so it can adapt mid-task (e.g. read memory, then search knowledge, then create a GitHub issue) without any brittle if/else routing. Failed tools are logged and the loop continues.

---

## Component Design

### Interface — `telegram_handler/handler.py`
Owns the Telegram `Application` and its own event loop (`run_polling`). Enforces the `TELEGRAM_ALLOWED_USERS` whitelist, registers slash commands, initializes the MCP coordinator in `post_init`, and forwards plain text to `Router.process(...)`. Long replies are auto-split under Telegram's 4096-char limit.

### Engine — `engine/router.py`
The `Router` runs the **Plan → Execute → Respond** loop described above. It talks to the local LLM over the OpenAI-compatible `/chat/completions` endpoint via `httpx`, builds the tool list from the `ToolRegistry`, executes tool calls, and persists each turn. (It also keeps a few legacy helper methods used by older skill handlers.)

### Capability router — `skills/tool_registry.py`
`ToolRegistry` merges **everything the model can do** into one flat OpenAI-format tool list:
- **Memory tools:** `memory_get_history`, `memory_get_facts`, `memory_save_fact`, `memory_get_today_log`
- **RAG tool:** `knowledge_search`
- **Skill tools:** one `skill_<name>` per loaded skill
- **MCP tools:** every dynamically discovered `<server>__<tool>`

It also dispatches each tool call to the right subsystem.

### MCP coordinator — `mcp/coordinator.py` + `mcp/client.py`
Spawns each MCP server as a subprocess and speaks **JSON-RPC 2.0 over stdio**. Tools are discovered **dynamically** via `tools/list` — nothing is hardcoded — and namespaced as `<server>__<tool>` (e.g. `github__create_issue`). Server launch commands are cross-platform (`npx` resolved via `shutil.which`). Each server is enabled only when its credentials are present in `.env`.

### Skills — `skills/executor.py`
Loads two kinds of skills:
1. **YAML prompt skills** — `skills/*.yaml` (a `name`, `description`, `tags`, optional `tools`, and a `prompt_template`).
2. **Python handler skills** — a subdirectory with `skill.yaml` + `handler.py` exposing an async `run(...)` (e.g. `skills/meeting_assistant/`).

### Memory — `memory_store/memory.py`
Manages the layered memory files and in-memory + JSONL-persisted conversation history (see [Memory System](#memory-system)).

### RAG — `rag/retriever.py`
ChromaDB vector store + `sentence-transformers` embeddings (`all-MiniLM-L6-v2`), paragraph-aware chunking (512 chars / 64 overlap), cosine similarity with a configurable score threshold.

### Config — `config/settings.py`
Loads all settings from `.env`, applies sensible defaults, ensures data directories exist, and exposes a `validate()` check for required values.

---

## File Structure

```
LocalMind/
├── main.py                          # Entry point — boots all subsystems, starts the bot
├── requirements.txt                 # Python dependencies
├── .env.example                     # Config template (copy to .env)
├── Dockerfile                       # Container image
├── docker-compose.yml               # Compose service + volumes + healthcheck
├── test_mcp.py                      # Standalone MCP stdio smoke-test script
│
├── config/
│   ├── __init__.py
│   └── settings.py                  # Loads .env → Settings, creates data dirs
│
├── telegram_handler/
│   ├── __init__.py
│   └── handler.py                   # Telegram bot: security gate, commands, dispatch
│
├── engine/
│   ├── __init__.py
│   ├── router.py                    # LLM-first Plan → Execute → Respond loop
│   └── intent_classifier.py         # Legacy rule/LLM intent tagging (not in active path)
│
├── skills/
│   ├── __init__.py
│   ├── tool_registry.py             # Flattens Memory + RAG + Skills + MCP into one tool list
│   ├── executor.py                  # Loads & runs YAML and Python skills
│   ├── summarize.yaml               # ┐
│   ├── scan_bugs.yaml               # │ default YAML prompt skills
│   ├── draft_message.yaml           # │
│   ├── github_workflow.yaml         # │
│   ├── telegram_manage.yaml         # │
│   ├── file_manager.yaml            # ┘
│   └── meeting_assistant/           # Python handler skill (record → transcribe → summarize)
│       ├── skill.yaml
│       ├── handler.py
│       └── meeting/
│           ├── recorder.py          # Mic capture (sounddevice)
│           ├── transcriber.py       # Whisper speech-to-text
│           ├── summarizer.py        # LLM summary + per-speaker notes
│           └── scheduler.py         # APScheduler auto start/stop
│
├── memory_store/
│   ├── __init__.py
│   └── memory.py                    # SOUL/TOOLS/USER/MEMORY + history persistence
│
├── rag/
│   ├── __init__.py
│   └── retriever.py                 # ChromaDB indexing + semantic retrieval
│
├── mcp/
│   ├── __init__.py
│   ├── coordinator.py               # Spawns MCP servers, dynamic tool discovery + routing
│   ├── client.py                    # JSON-RPC 2.0 stdio client (threaded reader)
│   ├── SETUP.md                     # MCP server setup notes
│   └── mcp_config_reference.json    # Reference config for external MCP clients
│
├── scripts/
│   ├── gen_telegram_session.py      # One-time Telegram session-string generator
│   └── index_docs.py                # Manual RAG indexer (--file/--dir/--stats/--clear)
│
├── tests/
│   ├── __init__.py
│   └── test_all.py                  # Component test suite
│
└── data/                            # Runtime data (gitignored where sensitive)
    ├── memory/                      # SOUL.md, TOOLS.md, MEMORY_*.md, USER_*.md, history_*.jsonl
    ├── chroma_db/                   # ChromaDB vector store (auto-created)
    ├── daily_logs/                  # YYYY-MM-DD.md conversation logs
    ├── meetings/                    # audio/ + transcripts/ from the meeting assistant
    └── logs/                        # Application logs
```

---

## MCP Servers

LocalMind integrates 5 MCP servers. Each is enabled only when its credentials are configured. Tools are discovered dynamically at startup and exposed to the model as `<server>__<tool>` (for example `filesystem__read_file`, `github__create_issue`, `telegram__send_message`).

### 1. Telegram MCP
**Source:** [chigwell/telegram-mcp](https://github.com/chigwell/telegram-mcp)
**What it does:** Lets the bot act on your **personal Telegram account** (not just bot-to-user), via Telethon — messaging, chats, groups, contacts, media, and more (60+ tools).

**Setup:**
1. Get API credentials at [my.telegram.org/apps](https://my.telegram.org/apps)
2. Generate a session string: `python scripts/gen_telegram_session.py`
3. Add to `.env`: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_SESSION_STRING`
4. (Recommended) Clone the server and set `TELEGRAM_MCP_DIR` to its path.

> ⚠️ **Security:** The session string grants full access to your Telegram account. Never commit it.

### 2. GitHub MCP
**Source:** [github/github-mcp-server](https://github.com/github/github-mcp-server)
**What it does:** Full GitHub integration — issues, PRs, code search, file reads, branches.

**Setup:**
1. Create a Personal Access Token at [github.com/settings/tokens](https://github.com/settings/tokens) (scopes: `repo`, `issues`, `pull_requests`)
2. Add to `.env`: `GITHUB_TOKEN=ghp_xxx...`

### 3. Filesystem MCP
**Source:** [modelcontextprotocol/servers/filesystem](https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem)
**What it does:** Read, write, search, and manage local files within allowed roots.
**Setup:** Always enabled. Requires Node.js (`npx` auto-installs the server on first run).

### 4. Windows MCP
**Source:** [CursorTouch/Windows-MCP](https://github.com/CursorTouch/Windows-MCP)
**What it does:** Computer use on Windows — screenshots, click, type, launch apps, run commands.
**Setup:** Auto-enabled on Windows only (no-op on macOS/Linux).

### 5. LinkedIn MCP
**Source:** [stickerdaniel/linkedin-mcp-server](https://github.com/stickerdaniel/linkedin-mcp-server)
**What it does:** LinkedIn profile lookup, job search, and posting.
**Setup:** Add `LINKEDIN_EMAIL` and `LINKEDIN_PASSWORD` to `.env`.

---

## Quick Start

### Prerequisites
- Python 3.11+
- Node.js (for the Filesystem/GitHub MCP servers via `npx`)
- A Telegram account + Bot token (from [@BotFather](https://t.me/BotFather))
- [Ollama](https://ollama.com) running locally (`ollama serve`) with a model pulled, e.g. `ollama pull kimi-k2.5:cloud`

### 1. Clone and configure
```bash
git clone <your-repo>
cd LocalMind---Local-AI-Personal-Assistant-with-Agentic-Capabilities-
cp .env.example .env
# Edit .env with your credentials
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure the Telegram bot
1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, follow the prompts.
2. Copy the token into `.env` as `TELEGRAM_BOT_TOKEN`.
3. (Recommended) Set `TELEGRAM_ALLOWED_USERS` to your numeric user ID.

### 4. Run
```bash
python main.py
```

### 5. Chat with your bot
Open Telegram and message your bot. Try:
- `/start`, `/help`, `/skills`, `/status`, `/memory`, `/clear`, `/index`
- "What did we discuss yesterday?"
- "Create a GitHub issue for bug X"
- "summarize this: …"
- "start meeting recording" / "summarize last meeting"

---

## Configuration

All configuration lives in `.env`. Key settings:

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_BASE_URL` | OpenAI-compatible LLM endpoint (Ollama) | `http://localhost:11434/v1` |
| `LLM_API_KEY` | API key for the endpoint (Ollama ignores it) | `ollama` |
| `LLM_MODEL` | Model name to use | `kimi-k2.5:cloud` |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather | required |
| `TELEGRAM_ALLOWED_USERS` | Comma-separated user IDs (empty = allow all) | |
| `GITHUB_TOKEN` | GitHub PAT (enables GitHub MCP) | |
| `TELEGRAM_MCP_DIR` | Path to a cloned telegram-mcp repo | |
| `RAG_TOP_K` | Max RAG results per query | `5` |
| `RAG_MIN_SCORE` | Minimum similarity score (0–1) | `0.3` |
| `MAX_CONVERSATION_HISTORY` | Turns included in context | `20` |
| `EMBEDDING_MODEL` | Sentence-transformer model | `all-MiniLM-L6-v2` |
| `BOT_NAME` | Display name | `LocalMind` |

See `.env.example` for the full annotated list.

---

## Skills System

Skills are reusable capabilities the model can invoke as `skill_<name>` tools.

**YAML prompt skills** (`skills/*.yaml`):
```yaml
name: my_skill
description: Does my custom thing
version: "1.0"
tags: [custom]
triggers:
  - '\bmy\s+skill\b'
tools: []          # optional MCP tool names to restrict to
prompt_template: |
  Perform this custom task:
  {{message}}
```

**Python handler skills** — a folder with `skill.yaml` + `handler.py` exposing `async def run(message, user_id, router)`. The bundled `meeting_assistant` records the mic, transcribes with Whisper, and produces an LLM summary with per-speaker notes.

**Default skills:** `summarize`, `scan_bugs`, `draft_message`, `github_workflow`, `telegram_manage`, `file_manager`, `meeting_assistant`.

---

## Memory System

| File | Scope | Description |
|------|-------|-------------|
| `SOUL.md` | Global | Bot persona — who it is, how it behaves |
| `TOOLS.md` | Global | Environment notes about available tools |
| `USER_{id}.md` | Per-user | User preferences and context |
| `MEMORY_{id}.md` | Per-user | Curated facts the bot has learned |
| `history_{id}.jsonl` | Per-user | Full conversation history |
| `daily_logs/YYYY-MM-DD.md` | Global | All interactions logged by day |

Edit `data/memory/SOUL.md` to change the persona. The model can also save facts itself via the `memory_save_fact` tool.

---

## RAG Knowledge Base

Semantic search over your documents (ChromaDB + sentence-transformers).

**Auto-indexed:** everything in `data/memory/` and the last 30 days of `data/daily_logs/`.

```bash
python scripts/index_docs.py --file /path/to/doc.md   # index one file
python scripts/index_docs.py --dir /path/to/docs/     # index a directory
python scripts/index_docs.py --stats                  # show chunk count
python scripts/index_docs.py --clear --dir data/memory/  # rebuild
```
Or send `/index` in Telegram to re-index memory files.

---

## Running Tests

```bash
python tests/test_all.py
```

Covers: module imports, memory store, RAG retriever (skipped if optional deps missing), skill executor, the MCP coordinator (dynamic tool discovery + a filesystem tool call), and the legacy intent classifier.

---

## Docker Deployment

```bash
docker compose up --build -d   # build and run
docker compose logs -f         # view logs
docker compose down            # stop
```
Data is persisted via the `./data` volume mount. Note: Ollama must be reachable from the container — point `LLM_BASE_URL` at your host (e.g. `http://host.docker.internal:11434/v1`).

---

## Troubleshooting

**Bot not responding**
- Verify `TELEGRAM_BOT_TOKEN` is correct and your ID is in `TELEGRAM_ALLOWED_USERS`.
- Check `data/logs/localmind.log`.

**"Cannot connect to Ollama"**
- Make sure `ollama serve` is running and the model in `LLM_MODEL` is pulled.
- Confirm `LLM_BASE_URL` (default `http://localhost:11434/v1`).

**MCP server not connecting**
- Run `/status` in Telegram to see which servers are enabled.
- Ensure that server's credentials are in `.env`, and that Node.js/`npx` (Filesystem, GitHub) or `uv`/`uvx` (Telegram, Windows, LinkedIn) is installed.

**RAG returns nothing**
- `python scripts/index_docs.py --stats` to check the chunk count.
- If 0: `python scripts/index_docs.py --dir data/memory/`; try lowering `RAG_MIN_SCORE`.

**Wrong / stale memory**
- Send `/clear` to reset conversation history, or edit `data/memory/MEMORY_{your_id}.md`.

---

## Security Notes

- Never commit `.env` — it's in `.gitignore`.
- The Telegram session string grants full account access; keep it secret.
- Set `TELEGRAM_ALLOWED_USERS` to your own user ID to lock the bot down.
- Find your Telegram user ID via [@userinfobot](https://t.me/userinfobot).
