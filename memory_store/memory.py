"""
LocalMind Memory Store
Manages all memory layers:
  - SOUL.md     (bot persona — global)
  - USER.md     (user preferences — per user)
  - MEMORY.md   (curated facts — per user)
  - TOOLS.md    (environment notes — global)
  - Conversation history (per user, in-memory + persisted)
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger


DEFAULT_SOUL = """You are LocalMind — an intelligent, helpful, and personable AI assistant.
You have access to tools that can interact with GitHub, Telegram, Windows OS, the filesystem, and LinkedIn.
You have a strong memory and can recall past conversations.
You are direct, efficient, and genuinely helpful. You don't pad responses with filler.
When you use tools, you explain what you're doing. When you find information in memory, you cite it naturally.
"""

DEFAULT_TOOLS_CONTEXT = """You have access to the following MCP tools:
- GitHub MCP: create issues, PRs, repos, manage code
- Telegram MCP: read/send messages, manage groups/channels (via your personal account)
- Windows MCP: take screenshots, control applications, type/click
- Filesystem MCP: read/write/list files and directories
- LinkedIn MCP: read and post on LinkedIn
"""


class MemoryStore:
    """
    Manages all memory layers for LocalMind.
    Per-user conversation history is kept in-memory (deque) and persisted as JSONL.
    Global persona files (SOUL.md, TOOLS.md) are on disk.
    """

    def __init__(self, memory_dir: str):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # In-memory conversation histories: {user_id: [{"role": ..., "content": ...}]}
        self._histories: Dict[int, List[dict]] = {}

        # Cache for file-based memory
        self._soul: Optional[str] = None
        self._tools_context: Optional[str] = None

    async def initialize(self):
        """Create default memory files if they don't exist."""
        # SOUL.md — global persona
        soul_path = self.memory_dir / "SOUL.md"
        if not soul_path.exists():
            soul_path.write_text(DEFAULT_SOUL, encoding="utf-8")
            logger.info("Created default SOUL.md")

        # TOOLS.md — global environment notes
        tools_path = self.memory_dir / "TOOLS.md"
        if not tools_path.exists():
            tools_path.write_text(DEFAULT_TOOLS_CONTEXT, encoding="utf-8")
            logger.info("Created default TOOLS.md")

        logger.info(f"MemoryStore initialized at {self.memory_dir}")

    # ── File-based Memory ─────────────────────────────────
    async def get_soul(self) -> str:
        """Load SOUL.md (bot persona)."""
        soul_path = self.memory_dir / "SOUL.md"
        if soul_path.exists():
            return soul_path.read_text(encoding="utf-8")
        return DEFAULT_SOUL

    async def get_tools_context(self) -> str:
        """Load TOOLS.md (environment notes)."""
        tools_path = self.memory_dir / "TOOLS.md"
        if tools_path.exists():
            return tools_path.read_text(encoding="utf-8")
        return DEFAULT_TOOLS_CONTEXT

    async def get_user_prefs(self, user_id: int) -> str:
        """Load per-user USER.md preferences."""
        user_path = self.memory_dir / f"USER_{user_id}.md"
        if user_path.exists():
            return user_path.read_text(encoding="utf-8")
        return ""

    async def set_user_prefs(self, user_id: int, content: str):
        """Save per-user preferences."""
        user_path = self.memory_dir / f"USER_{user_id}.md"
        user_path.write_text(content, encoding="utf-8")

    async def get_memory_facts(self, user_id: int) -> str:
        """Load per-user MEMORY.md (curated facts)."""
        mem_path = self.memory_dir / f"MEMORY_{user_id}.md"
        if mem_path.exists():
            return mem_path.read_text(encoding="utf-8")
        return ""

    async def save_memory_fact(self, user_id: int, fact: str):
        """Append a fact to the user's MEMORY.md."""
        mem_path = self.memory_dir / f"MEMORY_{user_id}.md"
        ts = datetime.now().strftime("%Y-%m-%d")
        with open(mem_path, "a", encoding="utf-8") as f:
            f.write(f"\n- [{ts}] {fact}")

    async def get_summary(self, user_id: int) -> str:
        """Return a summary of all memory layers for display."""
        soul = await self.get_soul()
        user_prefs = await self.get_user_prefs(user_id)
        facts = await self.get_memory_facts(user_id)
        history_len = len(self._histories.get(user_id, []))

        lines = [
            f"**SOUL.md**: {len(soul)} chars",
            f"**TOOLS.md**: loaded",
            f"**USER.md**: {'loaded' if user_prefs else 'not set'}",
            f"**MEMORY.md**: {'loaded (' + str(len(facts.splitlines())) + ' facts)' if facts else 'empty'}",
            f"**Conversation history**: {history_len} messages",
        ]
        return "\n".join(lines)

    # ── Conversation History ──────────────────────────────
    async def get_history(self, user_id: int, max_turns: int = 20) -> List[dict]:
        """Return the last max_turns messages for a user."""
        history = self._histories.get(user_id, [])
        return history[-max_turns:]

    async def add_turn(self, user_id: int, user_message: str, assistant_response: str):
        """Append a user/assistant turn to history and persist it."""
        if user_id not in self._histories:
            self._histories[user_id] = await self._load_history(user_id)

        self._histories[user_id].append({"role": "user", "content": user_message})
        self._histories[user_id].append({"role": "assistant", "content": assistant_response})

        # Keep last 200 messages in memory
        if len(self._histories[user_id]) > 200:
            self._histories[user_id] = self._histories[user_id][-200:]

        # Persist
        await self._persist_turn(user_id, user_message, assistant_response)

    async def clear_history(self, user_id: int):
        """Clear conversation history for a user."""
        self._histories[user_id] = []
        hist_path = self.memory_dir / f"history_{user_id}.jsonl"
        if hist_path.exists():
            hist_path.unlink()
        logger.info(f"Cleared history for user {user_id}")

    # ── Persistence ───────────────────────────────────────
    async def _load_history(self, user_id: int) -> List[dict]:
        """Load persisted conversation history from JSONL file."""
        hist_path = self.memory_dir / f"history_{user_id}.jsonl"
        if not hist_path.exists():
            return []
        turns = []
        try:
            with open(hist_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entry = json.loads(line)
                        turns.append({"role": "user", "content": entry["user"]})
                        turns.append({"role": "assistant", "content": entry["assistant"]})
        except Exception as e:
            logger.warning(f"Failed to load history for {user_id}: {e}")
        return turns[-200:]  # last 200 messages

    async def _persist_turn(self, user_id: int, user_message: str, assistant_response: str):
        """Append a turn to the JSONL history file."""
        hist_path = self.memory_dir / f"history_{user_id}.jsonl"
        entry = {
            "ts": datetime.now().isoformat(),
            "user": user_message,
            "assistant": assistant_response,
        }
        with open(hist_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
