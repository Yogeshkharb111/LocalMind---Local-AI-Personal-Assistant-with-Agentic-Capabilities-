"""
LocalMind Intent Classifier — Layer 1
Tags every incoming message with one of four intents before anything expensive runs.

Intents:
  CHAT   — pure conversation, no tools needed
  QUERY  — factual question likely answered by RAG / memory
  ACTION — requires an external MCP tool
  SKILL  — matches a named skill by name/trigger
"""

import re
from enum import Enum
from typing import Optional, List, Dict
from loguru import logger


class Intent(str, Enum):
    CHAT = "CHAT"
    QUERY = "QUERY"
    ACTION = "ACTION"
    SKILL = "SKILL"


# ── Rule-based patterns ────────────────────────────────────────────────────────

ACTION_KEYWORDS = [
    # GitHub
    r"\bcreate\s+(a\s+)?(github\s+)?(issue|pr|pull\s+request|repo|branch)\b",
    r"\b(open|close|merge)\s+(issue|pr|pull\s+request)\b",
    r"\bpush\s+to\b",
    r"\bcommit\b",
    # Telegram (via MCP)
    r"\bsend\s+(a\s+)?(message|msg|dm)\b",
    r"\bforward\s+(a\s+)?message\b",
    r"\bpin\s+(a\s+)?message\b",
    r"\b(mute|unmute|archive|unarchive)\s+(chat|group|channel)\b",
    r"\bget\s+(my\s+)?(chats|messages|history)\b",
    # Filesystem
    r"\b(read|write|create|delete|move|copy)\s+(a\s+)?(file|folder|directory)\b",
    r"\blist\s+(files|folders|directory|dir)\b",
    r"\bsearch\s+(files|folders)\b",
    # Windows
    r"\b(open|launch|start|close|kill)\s+(app|application|program|process)\b",
    r"\btake\s+(a\s+)?screenshot\b",
    r"\b(type|click|press|scroll)\b",
    # LinkedIn
    r"\b(post|share|like|comment)\s+(on\s+)?(linkedin|li)\b",
    r"\blinkedin\s+(job|post|profile|connection)\b",
    # General scheduling/reminders
    r"\b(remind\s+me|set\s+(a\s+)?reminder|schedule)\b",
    r"\bnotify\s+me\b",
]

QUERY_KEYWORDS = [
    r"\bwhat\s+(did|happened|was|were|is|are)\b",
    r"\bwhen\s+(did|was|were|is|are)\b",
    r"\bwho\s+(is|was|said|told)\b",
    r"\bhow\s+(did|does|can|many|much)\b",
    r"\bwhy\s+(did|is|was|are)\b",
    r"\b(did\s+we|we\s+decided|we\s+agreed|we\s+discussed)\b",
    r"\b(earlier|last\s+(week|month|time)|previously|you\s+said|i\s+told\s+you)\b",
    r"\bdo\s+you\s+remember\b",
    r"\bwhat.{0,20}(decided|agreed|discussed|mentioned)\b",
    r"\b(find|search|look\s+up)\s+(in\s+)?(memory|notes|history|knowledge)\b",
    r"\btell\s+me\s+about\b",
    r"\bexplain\b",
    r"\bsummariz(e|ation)\b",
]

CHAT_PATTERNS = [
    r"^(hi|hello|hey|howdy|sup|yo|morning|good\s+(morning|afternoon|evening|night))[\s!.?]*$",
    r"^(thanks?|thank\s+you|thx|ty|cheers|great|awesome|nice|cool|ok|okay|got\s+it|sure|yep|yeah|no|nope)[\s!.?]*$",
    r"^(bye|goodbye|see\s+ya|later|ttyl|gotta\s+go)[\s!.?]*$",
    r"^(haha|lol|lmao|hehe|😂|😄|👍|❤️|🙏)[\s!.?]*$",
    r"^(how\s+are\s+you|how.{0,10}doing|what.{0,10}up)[\?!.]*$",
]


class IntentClassifier:
    """
    Rule-based intent classifier (fast, free, deterministic).
    Falls back to LLM-based classification if mode='llm'.
    """

    def __init__(self, mode: str = "rule", skill_triggers: Optional[Dict[str, List[str]]] = None):
        self.mode = mode
        self.skill_triggers: Dict[str, List[str]] = skill_triggers or {}

        # Compile all patterns once
        self._action_re = [re.compile(p, re.IGNORECASE) for p in ACTION_KEYWORDS]
        self._query_re = [re.compile(p, re.IGNORECASE) for p in QUERY_KEYWORDS]
        self._chat_re = [re.compile(p, re.IGNORECASE) for p in CHAT_PATTERNS]

        logger.info(f"IntentClassifier initialized (mode={mode})")

    def update_skill_triggers(self, triggers: Dict[str, List[str]]):
        """Called by SkillExecutor after skills are loaded."""
        self.skill_triggers = triggers
        logger.debug(f"Updated skill triggers: {list(triggers.keys())}")

    def classify(self, message: str) -> tuple[Intent, Optional[str]]:
        """
        Classify a message. Returns (Intent, skill_name_if_SKILL).
        Uses rule-based matching (fast path) or LLM (if mode='llm').
        """
        if self.mode == "llm":
            return self._classify_llm(message)
        return self._classify_rules(message)

    def _classify_rules(self, message: str) -> tuple[Intent, Optional[str]]:
        msg = message.strip()

        # 1. Check SKILL triggers first (most specific)
        for skill_name, patterns in self.skill_triggers.items():
            for pattern in patterns:
                if re.search(pattern, msg, re.IGNORECASE):
                    logger.debug(f"Intent=SKILL (skill={skill_name})")
                    return Intent.SKILL, skill_name

        # 2. Check ACTION keywords
        for pattern in self._action_re:
            if pattern.search(msg):
                logger.debug(f"Intent=ACTION (matched: {pattern.pattern[:40]})")
                return Intent.ACTION, None

        # 3. Check QUERY keywords
        for pattern in self._query_re:
            if pattern.search(msg):
                logger.debug(f"Intent=QUERY (matched: {pattern.pattern[:40]})")
                return Intent.QUERY, None

        # 4. Check CHAT patterns (simple greetings/reactions)
        for pattern in self._chat_re:
            if pattern.match(msg):
                logger.debug("Intent=CHAT (greeting/reaction pattern)")
                return Intent.CHAT, None

        # 5. Heuristic: short messages with no question/action words → CHAT
        word_count = len(msg.split())
        if word_count <= 4 and "?" not in msg:
            logger.debug("Intent=CHAT (short message heuristic)")
            return Intent.CHAT, None

        # 6. Default: QUERY (anything ambiguous gets RAG lookup)
        logger.debug("Intent=QUERY (default fallback)")
        return Intent.QUERY, None

    def _classify_llm(self, message: str) -> tuple[Intent, Optional[str]]:
        """
        LLM-based classification (async wrapper).
        Note: This is a sync stub — in production, call via asyncio.
        """
        # Stub: fall back to rules for now (LLM version requires async)
        return self._classify_rules(message)

    async def classify_async_llm(self, message: str) -> tuple[Intent, Optional[str]]:
        """
        Async LLM-based intent classification using Ollama.
        Only used when INTENT_MODE=llm in .env.
        For most cases INTENT_MODE=rule is recommended (faster, free).
        """
        from config.settings import settings
        import httpx

        skill_list = ", ".join(self.skill_triggers.keys()) if self.skill_triggers else "none"
        prompt = (
            f"Classify this message into exactly ONE intent: CHAT, QUERY, ACTION, or SKILL.\n\n"
            f"Intents:\n"
            f"- CHAT: casual conversation, greetings, thanks, reactions\n"
            f"- QUERY: factual questions, memory recall, 'what did we decide', 'tell me about'\n"
            f"- ACTION: requests to DO something via tools (GitHub, Telegram, files, Windows)\n"
            f"- SKILL: matches a named skill ({skill_list})\n\n"
            f"Message: {message}\n\n"
            f"Reply with ONLY the intent label. One word only: CHAT, QUERY, ACTION, or SKILL."
        )

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{settings.LLM_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {settings.LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.LLM_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": 10,
                        "temperature": 0,
                    },
                )
                label = response.json()["choices"][0]["message"]["content"].strip().upper()
                # Strip any punctuation the model might add
                label = label.split()[0] if label else ""
                if label in Intent.__members__:
                    logger.debug(f"LLM classified intent: {label}")
                    return Intent(label), None
        except Exception as e:
            logger.warning(f"LLM classification failed, falling back to rules: {e}")

        return self._classify_rules(message)
