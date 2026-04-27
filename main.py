#!/usr/bin/env python3
"""
YogiBot — Main Entry Point
Layered Context Engine AI Assistant via Telegram
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from loguru import logger
from config.settings import settings
from telegram_handler.handler import TelegramHandler
from engine.router import Router
from mcp.coordinator import MCPCoordinator
from rag.retriever import RAGRetriever
from memory_store.memory import MemoryStore
from skills.executor import SkillExecutor


async def main():
    """Bootstrap all systems except MCP, return handler."""
    logger.info(f"🤖 Starting {settings.BOT_NAME} v{settings.BOT_VERSION}")
    logger.info("━" * 50)

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

    logger.info("🔧 Creating MCP Coordinator (will connect after Telegram starts)...")
    mcp_coord = MCPCoordinator()
    # ← NOT calling mcp_coord.initialize() here

    logger.info("🎯 Initializing Skill Executor...")
    skill_exec = SkillExecutor(settings.SKILLS_DIR)
    await skill_exec.initialize()

    logger.info("🚦 Initializing Router & Engine...")
    router = Router(
        memory=memory,
        rag=rag,
        mcp_coordinator=mcp_coord,
        skill_executor=skill_exec,
        intent_mode=settings.INTENT_MODE,
    )

    logger.info("📱 Initializing Telegram Handler...")
    handler = TelegramHandler(
        token=settings.TELEGRAM_BOT_TOKEN,
        allowed_users=settings.TELEGRAM_ALLOWED_USERS,
        router=router,
    )

    logger.info("📚 Checking RAG index...")
    await rag.index_memory_files(settings.MEMORY_DIR)

    logger.info(f"✅ {settings.BOT_NAME} ready!")
    logger.info("━" * 50)

    return handler  # ← return, don't run


if __name__ == "__main__":
    handler = asyncio.run(main())  # async init in ProactorEventLoop
    handler.run()                  # run_polling owns its own fresh loop