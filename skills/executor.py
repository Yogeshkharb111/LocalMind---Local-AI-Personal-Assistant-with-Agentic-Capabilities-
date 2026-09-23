"""
LocalMind Skill Executor — Layer 3a
Loads named skills from YAML definitions and executes them.

Two types of skills supported:
  1. YAML skills — defined in skills/*.yaml with prompt templates
  2. Python handler skills — subdirectories with skill.yaml + handler.py
     (e.g. skills/meeting_assistant/skill.yaml + handler.py)
"""

import importlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from loguru import logger


class Skill:
    """Represents a single loaded skill."""

    def __init__(self, data: dict):
        self.name: str = data["name"]
        self.description: str = data.get("description", "")
        self.triggers: List[str] = data.get("triggers", [])
        self.prompt_template: str = data.get("prompt_template", "")
        self.tools: List[str] = data.get("tools", [])
        self.version: str = data.get("version", "1.0")
        self.tags: List[str] = data.get("tags", [])
        # Python handler fields — set after init for handler-based skills
        self._is_python_handler: bool = False
        self._handler_module: Optional[str] = None

    def build_prompt(self, message: str, context: Dict[str, Any] = None) -> str:
        """Render the skill's prompt template."""
        ctx = {"message": message, **(context or {})}
        prompt = self.prompt_template
        for key, val in ctx.items():
            prompt = prompt.replace(f"{{{{{key}}}}}", str(val))
        return prompt


class SkillExecutor:
    """
    Loads skill definitions and executes them.
    Supports both YAML prompt-based skills and Python handler-based skills.
    """

    def __init__(self, skills_dir: str):
        self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, Skill] = {}
        self.version = "2.0.0"

    async def initialize(self):
        """Load all skills from the skills directory."""
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        await self._ensure_default_skills()
        await self._load_skills()
        logger.info(f"SkillExecutor: loaded {len(self.skills)} skills")

    async def _load_skills(self):
        """
        Load skills from two sources:
          1. *.yaml files directly in skills_dir (YAML prompt-based skills)
          2. Subdirectories containing both skill.yaml + handler.py (Python skills)
        """
        self.skills = {}

        # ── 1. YAML prompt-based skills ───────────────────
        for yaml_file in self.skills_dir.glob("*.yaml"):
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if data and "name" in data:
                    skill = Skill(data)
                    self.skills[skill.name] = skill
                    logger.debug(f"Loaded skill: {skill.name}")
            except Exception as e:
                logger.warning(f"Failed to load skill {yaml_file}: {e}")

        # ── 2. Python handler-based skills ────────────────
        for skill_dir in self.skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            if skill_dir.name.startswith("_"):
                continue  # skip __pycache__ etc.

            handler_file = skill_dir / "handler.py"
            yaml_file = skill_dir / "skill.yaml"

            if not handler_file.exists() or not yaml_file.exists():
                continue  # not a Python skill folder

            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if not data or "name" not in data:
                    continue

                skill = Skill(data)
                skill._is_python_handler = True
                skill._handler_module = f"skills.{skill_dir.name}.handler"
                self.skills[skill.name] = skill
                logger.debug(f"Loaded skill: {skill.name}")

            except Exception as e:
                logger.warning(f"Failed to load Python skill '{skill_dir.name}': {e}")

    async def get_triggers(self) -> Dict[str, List[str]]:
        """Return {skill_name: [trigger_patterns]} for the IntentClassifier."""
        return {name: skill.triggers for name, skill in self.skills.items()}

    async def list_skills(self) -> List[dict]:
        """Return skill metadata list for display."""
        return [
            {
                "name": s.name,
                "description": s.description,
                "triggers": s.triggers,
                "tags": s.tags,
            }
            for s in self.skills.values()
        ]

    async def execute(self, skill_name: str, message: str, user_id: int, router) -> str:
        """Execute a named skill — routes to Python handler or YAML prompt."""
        skill = self.skills.get(skill_name)
        if not skill:
            return f"⚠️ Skill '{skill_name}' not found."

        logger.info(f"Executing skill: {skill_name}")

        # ── Python handler-based skill ─────────────────────
        if skill._is_python_handler:
            try:
                module = importlib.import_module(skill._handler_module)
                return await module.run(
                    message=message,
                    user_id=user_id,
                    router=router,
                )
            except Exception as e:
                logger.error(f"Python skill '{skill_name}' failed: {e}")
                return f"⚠️ Skill '{skill_name}' encountered an error: {str(e)}"

        # ── YAML prompt-based skill ────────────────────────
        prompt = skill.build_prompt(message=message)

        if skill.tools:
            context = await router._build_context(
                user_id=user_id,
                include_rag=True,
                include_tools=True,
            )
            tools = await router.mcp_coordinator.get_tools()
            if skill.tools:
                tools = [t for t in tools if t["name"] in skill.tools]
            return await router._call_llm_with_tools(
                system=context["system"] + f"\n\nSkill Mode: {skill.name}\n{skill.description}",
                history=context["history"],
                message=prompt,
                tools=tools,
            )
        else:
            context = await router._build_context(
                user_id=user_id,
                include_rag=True,
                include_tools=False,
            )
            return await router._call_llm(
                system=context["system"] + f"\n\nSkill Mode: {skill.name}\n{skill.description}",
                history=context["history"],
                message=prompt,
            )

    async def _ensure_default_skills(self):
        """Create default skill YAML files if registry is empty."""
        if list(self.skills_dir.glob("*.yaml")):
            return

        defaults = [
            {
                "name": "summarize",
                "description": "Summarize a conversation, document, or channel history",
                "version": "1.0",
                "tags": ["productivity", "text"],
                "triggers": [
                    r"\bsummariz(e|ation)\b",
                    r"\bsum\s+up\b",
                    r"\btl;?dr\b",
                    r"\bgive\s+me\s+(a\s+)?summary\b",
                ],
                "tools": [],
                "prompt_template": (
                    "Please provide a clear, structured summary of the following. "
                    "Organize by key points and decisions made.\n\n"
                    "Content to summarize:\n{{message}}"
                ),
            },
            {
                "name": "scan_bugs",
                "description": "Scan code or a description for bugs, issues, and improvement suggestions",
                "version": "1.0",
                "tags": ["code", "review"],
                "triggers": [
                    r"\bscan\s+(for\s+)?bugs?\b",
                    r"\b(find|look\s+for)\s+(bugs?|issues?|errors?)\b",
                    r"\bcode\s+review\b",
                    r"\bdebu[g]?\b",
                ],
                "tools": ["fs_read_file", "github_get_file"],
                "prompt_template": (
                    "Analyze the following code or description for bugs, potential issues, "
                    "performance problems, and improvement suggestions. "
                    "Be specific and actionable.\n\n"
                    "{{message}}"
                ),
            },
            {
                "name": "draft_message",
                "description": "Draft a professional message, email, or post",
                "version": "1.0",
                "tags": ["writing", "communication"],
                "triggers": [
                    r"\bdraft\s+(a\s+)?(message|email|post|response|reply)\b",
                    r"\bwrite\s+(a\s+)?(professional|formal|casual)\b",
                    r"\bhelp\s+me\s+(write|compose|craft)\b",
                ],
                "tools": [],
                "prompt_template": (
                    "Draft a professional message based on the following request. "
                    "Match the appropriate tone and format.\n\n"
                    "Request: {{message}}"
                ),
            },
            {
                "name": "github_workflow",
                "description": "Assist with GitHub operations: create issues, PRs, review code",
                "version": "1.0",
                "tags": ["github", "development"],
                "triggers": [
                    r"\b(create|open|file)\s+(a\s+)?github\s+(issue|ticket|bug\s+report)\b",
                    r"\bgithub\s+(workflow|task|action)\b",
                ],
                "tools": [
                    "github_create_issue",
                    "github_list_issues",
                    "github_create_pull_request",
                    "github_search_code",
                    "github_get_file",
                ],
                "prompt_template": (
                    "Help me with the following GitHub task. "
                    "Use the available GitHub tools to complete it.\n\n"
                    "Task: {{message}}"
                ),
            },
            {
                "name": "telegram_manage",
                "description": "Manage Telegram chats, send messages, search history",
                "version": "1.0",
                "tags": ["telegram", "messaging"],
                "triggers": [
                    r"\b(check|search)\s+(telegram|tg)\b",
                    r"\btelegram\s+(history|messages|chat)\b",
                    r"\bscan\s+(this\s+)?channel\b",
                ],
                "tools": [
                    "telegram_get_messages",
                    "telegram_list_chats",
                    "telegram_search_messages",
                    "telegram_send_message",
                ],
                "prompt_template": (
                    "Help me with the following Telegram task. "
                    "Use the Telegram tools available to you.\n\n"
                    "Task: {{message}}"
                ),
            },
            {
                "name": "file_manager",
                "description": "Read, write, search, and manage files on the filesystem",
                "version": "1.0",
                "tags": ["filesystem", "files"],
                "triggers": [
                    r"\b(organize|manage)\s+files?\b",
                    r"\bfile\s+(manager|management)\b",
                    r"\bfind\s+all\s+files?\b",
                ],
                "tools": [
                    "fs_read_file",
                    "fs_write_file",
                    "fs_list_directory",
                    "fs_search_files",
                ],
                "prompt_template": (
                    "Help me with the following file management task. "
                    "Use filesystem tools to complete it.\n\n"
                    "Task: {{message}}"
                ),
            },
        ]

        for skill_data in defaults:
            yaml_path = self.skills_dir / f"{skill_data['name']}.yaml"
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(skill_data, f, default_flow_style=False, allow_unicode=True)
        logger.info(f"Created {len(defaults)} default skills")