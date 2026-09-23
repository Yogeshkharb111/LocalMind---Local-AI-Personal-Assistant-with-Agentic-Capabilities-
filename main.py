#!/usr/bin/env python3
"""
LocalMind — Main Entry Point
LLM-First Architecture: Plan → Execute → Respond
No intent classifier. LLM decides everything.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger

from config.settings import settings
from engine.router import Router
from mcp.coordinator import MCPCoordinator
from memory_store.memory import MemoryStore
from rag.retriever import RAGRetriever
from skills.executor import SkillExecutor
from telegram_handler.handler import TelegramHandler


async def main():
    logger.info(f"🤖 Starting {settings.BOT_NAME} v{settings.BOT_VERSION}")
    logger.info("━" * 50)

    # Fail fast if required configuration is missing.
    errors = settings.validate()
    if errors:
        for err in errors:
            logger.error(f"Config error: {err}")
        logger.error("Fix your .env (copy from .env.example) and restart.")
        sys.exit(1)

    # Security warning: an empty whitelist means ANYONE can use the bot.
    if not settings.TELEGRAM_ALLOWED_USERS:
        logger.warning(
            "TELEGRAM_ALLOWED_USERS is empty — the bot will accept messages from "
            "ANYONE. Set it to your numeric Telegram user id(s) to lock it down."
        )

    logger.info("📦 Initializing Memory Store...")
    memory = MemoryStore(settings.MEMORY_DIR)
    await memory.initialize()

    logger.info("🧠 Initializing RAG Pipeline...")
    rag = RAGRetriever(
        persist_dir=settings.CHROMA_PERSIST_DIR,
        embedding_model=settings.EMBEDDING_MODEL,
        top_k=settings.RAG_TOP_K,
        min_score=settings.RAG_MIN_SCORE,
    )
    await rag.initialize()

    logger.info("🔧 Creating MCP Coordinator...")
    mcp_coord = MCPCoordinator()

    logger.info("🎯 Initializing Skill Executor...")
    skill_exec = SkillExecutor(settings.SKILLS_DIR)
    await skill_exec.initialize()

    logger.info("🚦 Initializing Router (LLM-First: Plan → Execute → Respond)...")
    router = Router(
        memory=memory,
        rag=rag,
        mcp_coordinator=mcp_coord,
        skill_executor=skill_exec,
    )

    logger.info("📱 Initializing Telegram Handler...")
    handler = TelegramHandler(
        token=settings.TELEGRAM_BOT_TOKEN,
        allowed_users=settings.TELEGRAM_ALLOWED_USERS,
        router=router,
    )

    logger.info("📚 Indexing memory files into RAG...")
    await rag.index_memory_files(settings.MEMORY_DIR)

    logger.info(f"✅ {settings.BOT_NAME} ready! (LLM-First mode)")
    logger.info("━" * 50)

    return handler


if __name__ == "__main__":
    handler = asyncio.run(main())
    handler.run()
