"""
LocalMind Telegram Handler
Security gate → command routing → message dispatch
"""


from loguru import logger
from telegram import BotCommand, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


class TelegramHandler:
    """
    Handles all Telegram interaction.
    - Security gate: checks allowed_users whitelist
    - Command routing: /start, /memory, /skills, /clear, /status
    - Message dispatch: forwards messages to the Router engine
    """

    def __init__(self, token: str, allowed_users: list[int], router):
        self.token = token
        self.allowed_users = allowed_users
        self.router = router
        self.app: Application | None = None

    # ── Post-init hook ───────────────────────────────────
    async def _post_init(self, application: Application):
        """Called by run_polling after its loop is running."""
        # Initialize MCP inside run_polling's event loop
        import asyncio
        loop = asyncio.get_event_loop()
        logger.info(f"Event loop type in _post_init: {type(loop).__name__}")
        await self.router.mcp_coordinator.initialize()

        await application.bot.set_my_commands([
            BotCommand("start", "Start LocalMind"),
            BotCommand("help", "Show help"),
            BotCommand("memory", "View current memory context"),
            BotCommand("skills", "List available skills"),
            BotCommand("clear", "Clear conversation history"),
            BotCommand("status", "Show bot status & MCP connections"),
            BotCommand("index", "Re-index documents into knowledge base"),
        ])
        logger.info("🤖 Telegram bot polling started")

    async def _post_shutdown(self, application: Application):
        """Called by run_polling on shutdown — release external resources."""
        try:
            await self.router.mcp_coordinator.shutdown()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"MCP shutdown error: {e}")
        try:
            await self.router.aclose()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Router HTTP client close error: {e}")
        logger.info("👋 Shutdown complete")

    # ── Bootstrap ────────────────────────────────────────
    def run(self):
        """
        Build and start the Telegram bot.
        NOTE: This function is synchronous because run_polling
        manages its own asyncio event loop internally.
        """

        self.app = (
            Application.builder()
            .token(self.token)
            .post_init(self._post_init)
            .post_shutdown(self._post_shutdown)
            .build()
        )

        # Register command handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("memory", self._cmd_memory))
        self.app.add_handler(CommandHandler("skills", self._cmd_skills))
        self.app.add_handler(CommandHandler("clear", self._cmd_clear))
        self.app.add_handler(CommandHandler("status", self._cmd_status))
        self.app.add_handler(CommandHandler("index", self._cmd_index))

        # Main message handler
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
        )

        # run_polling owns the event loop
        self.app.run_polling(drop_pending_updates=True)

    # ── Security Gate ─────────────────────────────────────
    def _is_allowed(self, user_id: int) -> bool:
        """Return True if user is allowed (or no whitelist configured)."""
        if not self.allowed_users:
            return True
        return user_id in self.allowed_users

    async def _gate(self, update: Update) -> bool:
        """Check access and send rejection if not allowed."""
        user_id = update.effective_user.id

        if not self._is_allowed(user_id):
            await update.message.reply_text(
                "⛔ Sorry, you are not authorized to use this bot."
            )
            logger.warning(f"Unauthorized access attempt from user {user_id}")
            return False

        return True

    # ── Commands ──────────────────────────────────────────
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._gate(update):
            return

        name = update.effective_user.first_name or "there"

        await update.message.reply_text(
            f"👋 Hey {name}! I'm LocalMind — your personal AI assistant.\n\n"
            f"I can:\n"
            f"• Answer questions using my memory and RAG knowledge base\n"
            f"• Execute tasks via MCP tools\n"
            f"• Run automation skills\n"
            f"• Have natural conversations\n\n"
            f"Use /help to see available commands.",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._gate(update):
            return

        help_text = (
            "*LocalMind Commands*\n\n"
            "/start — Welcome message\n"
            "/memory — Show memory context\n"
            "/skills — List available skills\n"
            "/clear — Clear conversation history\n"
            "/status — Show bot status\n"
            "/index — Re-index documents\n"
        )

        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

    async def _cmd_memory(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._gate(update):
            return

        user_id = update.effective_user.id
        memory_summary = await self.router.memory.get_summary(user_id)

        await update.message.reply_text(
            f"🧠 *Memory Context*\n\n{memory_summary}",
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_skills(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._gate(update):
            return

        skills_list = await self.router.skill_executor.list_skills()

        if not skills_list:
            await update.message.reply_text("No skills loaded yet.")
            return

        lines = ["🎯 *Available Skills*\n"]

        for skill in skills_list:
            lines.append(f"• *{skill['name']}* — {skill['description']}")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN
        )

    async def _cmd_clear(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._gate(update):
            return

        user_id = update.effective_user.id
        await self.router.memory.clear_history(user_id)

        await update.message.reply_text("🗑️ Conversation history cleared.")

    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._gate(update):
            return

        status = await self.router.mcp_coordinator.get_status()

        lines = ["📊 *LocalMind Status*\n"]

        for name, info in status.items():
            icon = "✅" if info["connected"] else "❌"
            lines.append(f"{icon} {name}: {info['status']}")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
        )

    async def _cmd_index(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._gate(update):
            return

        await update.message.reply_text("📚 Re-indexing knowledge base...")

        from config.settings import settings

        count = await self.router.rag.index_memory_files(settings.MEMORY_DIR)

        await update.message.reply_text(f"✅ Indexed {count} document chunks.")

    # ── Main Message Handler ──────────────────────────────
    async def _handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):

        if not await self._gate(update):
            return

        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "User"
        text = update.message.text.strip()

        logger.info(f"📨 [{user_name}:{user_id}] {text[:80]}...")

        await update.message.chat.send_action(ChatAction.TYPING)

        try:
            response = await self.router.process(
                user_id=user_id,
                user_name=user_name,
                message=text,
            )

            if len(response) > 4000:
                for i in range(0, len(response), 4000):
                    await update.message.reply_text(response[i:i+4000])
            else:
                await update.message.reply_text(response)

        except Exception as e:
            logger.exception(f"Error processing message from {user_id}: {e}")

            await update.message.reply_text(
                "⚠️ Something went wrong processing your message."
            )
