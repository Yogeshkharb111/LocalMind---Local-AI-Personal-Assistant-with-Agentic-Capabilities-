"""
LocalMind Tool Registry
Combines ALL tools into one flat list for the LLM:
  - Memory tools  (STM history, LTM facts, RAG search, daily log)
  - Skill tools   (summarize, scan_bugs, draft_message, etc.)
  - MCP tools     (Telegram, GitHub, Filesystem, Windows, LinkedIn)

LLM sees everything — it decides what to call and when.
"""

from loguru import logger


class ToolRegistry:

    def __init__(self, mcp_coordinator, skill_executor, memory, rag, daily_logs_dir: str):
        self.mcp_coordinator = mcp_coordinator
        self.skill_executor = skill_executor
        self.memory = memory
        self.rag = rag
        self.daily_logs_dir = daily_logs_dir

    async def get_all_tools(self) -> list:
        tools = []
        tools += self._memory_tools()
        tools += self._rag_tools()
        tools += await self._skill_tools()
        tools += await self._mcp_tools()
        logger.debug(f"ToolRegistry: {len(tools)} total tools available to LLM")
        return tools

    async def execute(self, tool_name: str, tool_args: dict, user_id: int, router) -> str:

        # ── Memory tools ──────────────────────────────────
        if tool_name == "memory_get_history":
            turns = tool_args.get("turns", 10)
            history = await self.memory.get_history(user_id, max_turns=turns * 2)
            if not history:
                return "No conversation history found."
            lines = []
            for msg in history[-turns * 2:]:
                role = "You" if msg["role"] == "user" else "LocalMind"
                lines.append(f"{role}: {msg['content']}")
            return "\n".join(lines)

        if tool_name == "memory_get_facts":
            facts = await self.memory.get_memory_facts(user_id)
            return facts if facts else "No long-term facts saved yet."

        if tool_name == "memory_save_fact":
            fact = tool_args.get("fact", "")
            if fact:
                await self.memory.save_memory_fact(user_id, fact)
                return f"Saved to long-term memory: {fact}"
            return "No fact provided."

        if tool_name == "memory_get_today_log":
            from datetime import datetime
            from pathlib import Path
            log_path = Path(self.daily_logs_dir) / f"{datetime.now().strftime('%Y-%m-%d')}.md"
            if log_path.exists():
                return log_path.read_text(encoding="utf-8")[:3000]
            return "No activity logged today yet."

        # ── RAG ───────────────────────────────────────────
        if tool_name == "knowledge_search":
            query = tool_args.get("query", "")
            if not query:
                return "No query provided."
            try:
                results = await self.rag.retrieve(query)
                if not results:
                    return "No relevant knowledge found."
                parts = [f"[{i+1}] (score: {r['score']:.2f}) {r['text']}" for i, r in enumerate(results)]
                return "\n".join(parts)
            except Exception as e:
                return f"Knowledge search failed: {e}"

        # ── Skill tools ───────────────────────────────────
        if tool_name.startswith("skill_"):
            skill_name = tool_name[len("skill_"):]
            message = tool_args.get("message", "")
            try:
                return await self.skill_executor.execute(
                    skill_name=skill_name,
                    message=message,
                    user_id=user_id,
                    router=router,
                )
            except Exception as e:
                logger.error(f"Skill tool '{skill_name}' failed: {e}")
                return f"Skill execution failed: {e}"

        # ── MCP tools ─────────────────────────────────────
        try:
            result = await self.mcp_coordinator.execute_tool(tool_name, tool_args)
            return str(result)
        except Exception as e:
            logger.error(f"MCP tool '{tool_name}' failed: {e}")
            return f"Tool execution failed: {e}"

    # ── Tool Definitions ──────────────────────────────────

    def _memory_tools(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "memory_get_history",
                    "description": "Retrieve recent conversation history (short-term memory). Use when the user refers to something said earlier or context from previous messages is needed.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "turns": {"type": "integer", "description": "Number of recent turns to retrieve (default: 10)", "default": 10}
                        },
                        "required": [],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_get_facts",
                    "description": "Retrieve long-term memory facts about this user. Use when you need persistent information like preferences, past decisions, or important context.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_save_fact",
                    "description": "Save an important fact to long-term memory. Use when the user shares something worth remembering permanently.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "fact": {"type": "string", "description": "The fact to remember, written concisely."}
                        },
                        "required": ["fact"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_get_today_log",
                    "description": "Get today's activity log — all interactions taken today. Use when asked 'what did we do today' or 'what happened today'.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
        ]

    def _rag_tools(self) -> list:
        return [
            {
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "description": "Search the knowledge base (indexed documents, notes, files). Use when the user asks about specific documents or project knowledge.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query to find relevant knowledge."}
                        },
                        "required": ["query"],
                    },
                },
            }
        ]

    async def _skill_tools(self) -> list:
        skill_list = await self.skill_executor.list_skills()
        tools = []
        for skill in skill_list:
            tools.append({
                "type": "function",
                "function": {
                    "name": f"skill_{skill['name']}",
                    "description": f"{skill['description']} Tags: {', '.join(skill.get('tags', []))}.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {
                                "type": "string",
                                "description": "The full instruction for this skill including all relevant details from the user's request.",
                            }
                        },
                        "required": ["message"],
                    },
                },
            })
        return tools

    async def _mcp_tools(self) -> list:
        mcp_tools = await self.mcp_coordinator.get_tools()
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                },
            }
            for t in mcp_tools
        ]
