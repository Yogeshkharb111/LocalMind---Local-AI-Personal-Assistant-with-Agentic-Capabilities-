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
from telegram_handler.handler import TelegramHandler
from engine.router import Router
from mcp.coordinator import MCPCoordinator
from rag.retriever import RAGRetriever
from memory_store.memory import MemoryStore
from skills.executor import SkillExecutor


async def main():
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
