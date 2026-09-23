"""
LocalMind Settings — loads from .env file
"""

import os
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent.parent / ".env")


class Settings:
    # ── LLM Backend — Ollama (local, no API key needed) ───
    # Ollama runs at localhost:11434 by default
    # Model shown in your Ollama UI: kimi-k2.5:cloud
    # Change LLM_MODEL in .env to switch models anytime
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    LLM_API_KEY:  str = os.getenv("LLM_API_KEY",  "ollama")   # dummy key — Ollama doesn't need one
    LLM_MODEL:    str = os.getenv("LLM_MODEL",    "kimi-k2.5:cloud")

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    _allowed_raw: str = os.getenv("TELEGRAM_ALLOWED_USERS", "")
    TELEGRAM_ALLOWED_USERS: List[int] = (
        [int(x.strip()) for x in _allowed_raw.split(",") if x.strip()]
        if _allowed_raw
        else []
    )

    # Telegram MCP (Telethon)
    TELEGRAM_API_ID: str = os.getenv("TELEGRAM_API_ID", "")
    TELEGRAM_API_HASH: str = os.getenv("TELEGRAM_API_HASH", "")
    TELEGRAM_SESSION_STRING: str = os.getenv("TELEGRAM_SESSION_STRING", "")

    # GitHub MCP
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")
    GITHUB_TOOLSETS: str = os.getenv("GITHUB_TOOLSETS", "repos,issues,pull_requests")

    # LinkedIn MCP
    LINKEDIN_EMAIL: str = os.getenv("LINKEDIN_EMAIL", "")
    LINKEDIN_PASSWORD: str = os.getenv("LINKEDIN_PASSWORD", "")

    # Telegram MCP server directory (clone of chigwell/telegram-mcp)
    # If set, bot uses: uv --directory <path> run main.py
    # If not set, bot tries: uvx telegram-mcp  (requires pip install telegram-mcp)
    TELEGRAM_MCP_DIR: str = os.getenv("TELEGRAM_MCP_DIR", "")

    # Allowed file roots for Telegram MCP file-path tools (send_file, download_media, etc.)
    # Space-separated paths. Defaults to home dir + /tmp
    TELEGRAM_MCP_FILE_ROOTS: str = os.getenv(
        "TELEGRAM_MCP_FILE_ROOTS",
        f"{os.path.expanduser('~')} /tmp"
    )

    # Windows MCP telemetry (set to "false" to disable)
    WINDOWS_MCP_TELEMETRY: str = os.getenv("WINDOWS_MCP_TELEMETRY", "false")

    # Bot Identity
    BOT_NAME: str = os.getenv("BOT_NAME", "LocalMind")
    BOT_VERSION: str = os.getenv("BOT_VERSION", "2.0.0")

    # RAG
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma_db")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    RAG_TOP_K: int = int(os.getenv("RAG_TOP_K", "5"))
    RAG_MIN_SCORE: float = float(os.getenv("RAG_MIN_SCORE", "0.3"))

    # Memory
    MEMORY_DIR: str = os.getenv("MEMORY_DIR", "./data/memory")
    MAX_CONVERSATION_HISTORY: int = int(os.getenv("MAX_CONVERSATION_HISTORY", "20"))

    # Intent
    INTENT_MODE: str = os.getenv("INTENT_MODE", "rule")  # 'rule' or 'llm'

    # Logging
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE: str = os.getenv("LOG_FILE", "./data/logs/localmind.log")

    # Paths
    SKILLS_DIR: str = os.getenv("SKILLS_DIR", "./skills")
    DAILY_LOGS_DIR: str = os.getenv("DAILY_LOGS_DIR", "./data/daily_logs")

    def validate(self) -> List[str]:
        """Return list of missing required settings."""
        errors = []
        if not self.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN is required")
        if not self.LLM_BASE_URL:
            errors.append("LLM_BASE_URL is required (default: http://localhost:11434/v1)")
        if not self.LLM_MODEL:
            errors.append("LLM_MODEL is required (default: kimi-k2.5:cloud)")
        return errors


settings = Settings()

# Ensure directories exist
for d in [
    settings.CHROMA_PERSIST_DIR,
    settings.MEMORY_DIR,
    settings.DAILY_LOGS_DIR,
    str(Path(settings.LOG_FILE).parent),
]:
    Path(d).mkdir(parents=True, exist_ok=True)
