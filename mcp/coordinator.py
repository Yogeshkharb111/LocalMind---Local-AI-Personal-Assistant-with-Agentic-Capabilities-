"""
LocalMind MCP Coordinator — Real MCP Subprocess Integration
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Spawns each MCP server as a real subprocess and communicates via JSON-RPC
stdio. Tools are discovered DYNAMICALLY from each server via tools/list —
nothing is hardcoded. Every tool the upstream repo exposes becomes available
to LocalMind automatically.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MCP SERVER 1: chigwell/telegram-mcp
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Source: https://github.com/chigwell/telegram-mcp
Install:
  git clone https://github.com/chigwell/telegram-mcp.git
  cd telegram-mcp && uv sync
  uv run session_string_generator.py   # generate TELEGRAM_SESSION_STRING
Launch command (from README):
  uv --directory /path/to/telegram-mcp run main.py [file_root1 file_root2 ...]
  OR if installed via pip install telegram-mcp:
  uvx telegram-mcp [file_root1 file_root2 ...]

Tools (63 total — all discovered dynamically via tools/list):
  Chat & Group: get_chats, list_chats, get_chat, create_group, invite_to_group,
    create_channel, edit_chat_title, leave_chat, get_participants, get_admins,
    get_banned_users, promote_admin, demote_admin, ban_user, unban_user,
    get_invite_link, export_chat_invite, import_chat_invite, join_chat_by_link,
    subscribe_public_channel, delete_chat_photo
  Messaging: get_messages, list_messages, list_topics, send_message,
    reply_to_message, edit_message, delete_message, forward_message,
    pin_message, unpin_message, mark_as_read, get_message_context,
    get_history, get_pinned_messages, get_last_interaction, create_poll,
    list_inline_buttons, press_inline_button, send_reaction, remove_reaction,
    get_message_reactions
  Contacts: list_contacts, search_contacts, add_contact, delete_contact,
    block_user, unblock_user, import_contacts, export_contacts,
    get_blocked_users, get_contact_ids, get_direct_chat_by_contact,
    get_contact_chats
  User/Profile: get_me, update_profile, delete_profile_photo,
    get_user_photos, get_user_status
  Media (requires TELEGRAM_MCP_FILE_ROOTS): send_file, download_media,
    set_profile_photo, edit_chat_photo, send_voice, send_sticker, upload_file
  Search: search_public_chats, search_messages, resolve_username
  Bots: get_sticker_sets, get_bot_info, set_bot_commands
  Privacy/Settings: get_privacy_settings, set_privacy_settings,
    mute_chat, unmute_chat, archive_chat, unarchive_chat, get_recent_actions
  Drafts: save_draft, get_drafts, clear_draft

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MCP SERVER 2: github/github-mcp-server
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Source: https://github.com/github/github-mcp-server
Launch command (from README):
  uvx github-mcp-server stdio
Env: GITHUB_PERSONAL_ACCESS_TOKEN

Tools (discovered dynamically — ~28 tools):
  Repos, Issues, PRs, Code Search, Files, Branches, Commits,
  Releases, Actions, Users, Orgs, Search, Fork, Star, Watch...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MCP SERVER 3: modelcontextprotocol/servers — filesystem
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Source: https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem
Launch command:
  npx -y @modelcontextprotocol/server-filesystem <allowed_dir1> <allowed_dir2>
No credentials needed.

Tools (discovered dynamically — ~8 tools):
  read_file, write_file, list_directory, search_files,
  create_directory, move_file, get_file_info, list_allowed_directories

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MCP SERVER 4: CursorTouch/Windows-MCP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Source: https://github.com/CursorTouch/Windows-MCP
PyPI: available as 'windows-mcp'
Launch command (from README):
  uvx windows-mcp
Env: ANONYMIZED_TELEMETRY=false (to disable telemetry)
Windows only (7, 8, 10, 11). Python 3.13+ required.

Tools (discovered dynamically):
  Click, Type, Scroll, Move, Shortcut, Wait, Snapshot,
  App, Shell, Scrape, MultiSelect, MultiEdit, Clipboard,
  Process, Notification, Registry

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MCP SERVER 5: stickerdaniel/linkedin-mcp-server
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Source: https://github.com/stickerdaniel/linkedin-mcp-server
Launch command:
  uvx linkedin-mcp-server
Env: LINKEDIN_EMAIL, LINKEDIN_PASSWORD

Tools (discovered dynamically):
  get_profile, search_jobs, search_people, get_company, get_job_details
"""

import asyncio
import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from loguru import logger

from mcp.client import MCPClient
from config.settings import settings


def _build_telegram_command() -> List[str]:
    """
    Build the correct command to launch chigwell/telegram-mcp.

    Priority:
      1. If TELEGRAM_MCP_DIR is set → use cloned repo:
         uv --directory <dir> run main.py [file_roots...]
      2. Otherwise → use installed package:
         uvx telegram-mcp [file_roots...]

    File roots (for send_file, download_media etc.) come from
    TELEGRAM_MCP_FILE_ROOTS (whitespace- or comma-separated paths).
    """
    # Accept whitespace- or comma-separated paths (matches the .env default,
    # which is space-separated).
    raw_roots = settings.TELEGRAM_MCP_FILE_ROOTS or ""
    file_roots = [p for p in re.split(r"[\s,]+", raw_roots.strip()) if p]

    if settings.TELEGRAM_MCP_DIR and Path(settings.TELEGRAM_MCP_DIR).exists():
        cmd = [
            "uv", "--directory", settings.TELEGRAM_MCP_DIR,
            "run", "main.py",
        ] + file_roots
        logger.info(f"Telegram MCP: using cloned repo at {settings.TELEGRAM_MCP_DIR}")
    else:
        cmd = ["uvx", "telegram-mcp"] + file_roots
        logger.info("Telegram MCP: using uvx telegram-mcp (install via: pip install telegram-mcp)")

    return cmd


def _npx_command() -> List[str]:
    """
    Return the platform-appropriate `npx` invocation.

    On Windows, npx is installed as `npx.cmd` and must be found on PATH; on
    Linux/macOS it is plain `npx`. Using shutil.which keeps this working
    regardless of where Node.js was installed.
    """
    if platform.system() == "Windows":
        return [shutil.which("npx.cmd") or shutil.which("npx") or "npx.cmd"]
    return [shutil.which("npx") or "npx"]


def _allowed_fs_roots() -> List[str]:
    """Directories the filesystem MCP server is allowed to touch."""
    home_dir = os.path.expanduser("~")
    roots = [home_dir]
    downloads_dir = Path(home_dir) / "Downloads"
    if downloads_dir.exists():
        roots.append(str(downloads_dir))
    return roots


def _build_filesystem_command() -> List[str]:
    """
    Build a cross-platform launch command for the filesystem MCP server.

    Prefers a globally installed server (launched via `node <index.js>` to
    avoid Windows shell-shim issues under subprocess execution) and otherwise
    falls back to `npx -y @modelcontextprotocol/server-filesystem`, which
    auto-installs it on first run.
    """
    home_dir = os.path.expanduser("~")
    roots = _allowed_fs_roots()

    # Windows global npm install path (node <index.js> avoids .cmd shim issues)
    npm_server = (
        Path(home_dir) / "AppData" / "Roaming" / "npm" / "node_modules"
        / "@modelcontextprotocol" / "server-filesystem" / "dist" / "index.js"
    )
    if npm_server.exists():
        return ["node", str(npm_server), *roots]

    return [*_npx_command(), "-y", "@modelcontextprotocol/server-filesystem", *roots]


def _server_definitions() -> List[dict]:
    """
    Build the list of all MCP server definitions.
    Each entry describes how to spawn one server as a subprocess.
    """
    defs = []

    # ── 1. Telegram MCP ───────────────────────────────────────────────────────
    # https://github.com/chigwell/telegram-mcp
    # 63 tools covering all of Telegram: messaging, groups, contacts, media,
    # privacy, drafts, bots, stickers, inline buttons, reactions, and more.
    telegram_env = {
        "TELEGRAM_API_ID": settings.TELEGRAM_API_ID,
        "TELEGRAM_API_HASH": settings.TELEGRAM_API_HASH,
        "TELEGRAM_SESSION_STRING": settings.TELEGRAM_SESSION_STRING,
        # SESSION_NAME is used if SESSION_STRING is empty (file-based sessions)
        "TELEGRAM_SESSION_NAME": "localmind_session",
    }
    defs.append({
        "name": "telegram",
        "command": _build_telegram_command(),
        "env": telegram_env,
        "enabled": bool(
            settings.TELEGRAM_API_ID
            and settings.TELEGRAM_API_HASH
            and settings.TELEGRAM_SESSION_STRING
        ),
        "timeout": 120,  # ← add this line
        "install_hint": (
            "Setup:\n"
            "  1. git clone https://github.com/chigwell/telegram-mcp.git\n"
            "  2. cd telegram-mcp && uv sync\n"
            "  3. uv run session_string_generator.py\n"
            "  4. Set TELEGRAM_MCP_DIR, TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING in .env\n"
            "  OR: pip install telegram-mcp  (then just set the env vars)"
        ),
        "expected_tools": [
            # Chat & Group Management
            "get_chats", "list_chats", "get_chat", "create_group",
            "invite_to_group", "create_channel", "edit_chat_title",
            "delete_chat_photo", "leave_chat", "get_participants",
            "get_admins", "get_banned_users", "promote_admin", "demote_admin",
            "ban_user", "unban_user", "get_invite_link", "export_chat_invite",
            "import_chat_invite", "join_chat_by_link", "subscribe_public_channel",
            # Messaging
            "get_messages", "list_messages", "list_topics", "send_message",
            "reply_to_message", "edit_message", "delete_message",
            "forward_message", "pin_message", "unpin_message", "mark_as_read",
            "get_message_context", "get_history", "get_pinned_messages",
            "get_last_interaction", "create_poll", "list_inline_buttons",
            "press_inline_button", "send_reaction", "remove_reaction",
            "get_message_reactions",
            # Contacts
            "list_contacts", "search_contacts", "add_contact", "delete_contact",
            "block_user", "unblock_user", "import_contacts", "export_contacts",
            "get_blocked_users", "get_contact_ids", "get_direct_chat_by_contact",
            "get_contact_chats",
            # User & Profile
            "get_me", "update_profile", "delete_profile_photo",
            "get_user_photos", "get_user_status",
            # Media (requires file roots configured)
            "send_file", "download_media", "set_profile_photo",
            "edit_chat_photo", "send_voice", "send_sticker", "upload_file",
            "get_media_info",
            # Search & Discovery
            "search_public_chats", "search_messages", "resolve_username",
            # Bots & Stickers
            "get_sticker_sets", "get_bot_info", "set_bot_commands",
            # Privacy, Settings
            "get_privacy_settings", "set_privacy_settings",
            "mute_chat", "unmute_chat", "archive_chat", "unarchive_chat",
            "get_recent_actions",
            # Drafts
            "save_draft", "get_drafts", "clear_draft",
        ],
    })

    # ── 2. GitHub MCP ─────────────────────────────────────────────────────────
    # https://github.com/github/github-mcp-server
    # Full GitHub API: repos, issues, PRs, code search, files, branches,
    # commits, releases, actions workflows, users, orgs.
    defs.append({
        "name": "github",
        "command": [*_npx_command(), "-y", "@modelcontextprotocol/server-github"],
        "env": {
            "GITHUB_PERSONAL_ACCESS_TOKEN": settings.GITHUB_TOKEN,
        },
        "enabled": bool(settings.GITHUB_TOKEN),
        "install_hint": (
            "Setup:\n"
            "  1. Create token at https://github.com/settings/tokens\n"
            "     Scopes: repo, read:org, issues, pull_requests\n"
            "  2. Set GITHUB_TOKEN in .env\n"
            "  uvx auto-downloads github-mcp-server on first run"
        ),
        "expected_tools": [
            "create_repository", "get_repository", "list_repositories",
            "search_repositories", "fork_repository", "create_branch",
            "list_branches", "create_issue", "get_issue", "list_issues",
            "update_issue", "add_issue_comment", "create_pull_request",
            "get_pull_request", "list_pull_requests", "merge_pull_request",
            "get_file_contents", "create_or_update_file", "push_files",
            "search_code", "list_commits", "get_commit",
            "create_release", "list_releases", "trigger_workflow",
            "list_workflow_runs", "search_users",
        ],
    })

    # ── 3. Filesystem MCP ────────────────────────────────────────────────────
    # https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem
    # Secure filesystem access. Paths must be within the allowed directories
    # passed as positional arguments to the server.
    defs.append({
        "name": "filesystem",
        "command": _build_filesystem_command(),
        "env": {},
        "enabled": True,
        "install_hint": (
            "Requires Node.js: https://nodejs.org\n"
            "npx will auto-install @modelcontextprotocol/server-filesystem on first run."
        ),
        "expected_tools": [
            "read_file", "write_file", "list_directory", "search_files",
            "create_directory", "move_file", "get_file_info",
            "list_allowed_directories",
        ],
    })

    # ── 4. Windows MCP ───────────────────────────────────────────────────────
    # https://github.com/CursorTouch/Windows-MCP
    # Available on PyPI as 'windows-mcp'.
    # Windows 7/8/10/11. Python 3.13+ required.
    # Tools: Click, Type, Scroll, Move, Shortcut, Wait, Snapshot,
    #        App, Shell, Scrape, MultiSelect, MultiEdit, Clipboard,
    #        Process, Notification, Registry
    defs.append({
        "name": "windows",
        "command": ["uvx", "windows-mcp"],
        "env": {
            # Disable telemetry as recommended in README
            "ANONYMIZED_TELEMETRY": settings.WINDOWS_MCP_TELEMETRY,
        },
        "enabled": platform.system() == "Windows",
        "install_hint": (
            "Windows only (7/8/10/11). Python 3.13+ required.\n"
            "Install uv: pip install uv\n"
            "Then: uvx windows-mcp  (auto-downloads from PyPI)"
        ),
        "expected_tools": [
            # Exact tool names from CursorTouch/Windows-MCP README
            "Click", "Type", "Scroll", "Move", "Shortcut", "Wait",
            "Snapshot", "App", "Shell", "Scrape", "MultiSelect",
            "MultiEdit", "Clipboard", "Process", "Notification", "Registry",
        ],
    })

    # ── 5. LinkedIn MCP ──────────────────────────────────────────────────────
    # https://github.com/stickerdaniel/linkedin-mcp-server
    # LinkedIn scraping: profiles, companies, jobs, people search.
    defs.append({
        "name": "linkedin",
        "command": ["uvx", "linkedin-mcp-server"],
        "env": {
            "LINKEDIN_EMAIL": settings.LINKEDIN_EMAIL,
            "LINKEDIN_PASSWORD": settings.LINKEDIN_PASSWORD,
        },
        "enabled": bool(settings.LINKEDIN_EMAIL and settings.LINKEDIN_PASSWORD),
        "install_hint": (
            "Setup:\n"
            "  1. Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in .env\n"
            "  2. uvx auto-downloads linkedin-mcp-server on first run"
        ),
        "expected_tools": [
            "get_profile", "search_jobs", "search_people",
            "get_company", "get_job_details",
        ],
    })

    return defs


class MCPCoordinator:
    """
    Manages all MCP server connections.

    Flow:
      initialize() → spawns subprocesses → JSON-RPC handshake → tools/list
      execute_tool() → tools/call via JSON-RPC → result string

    Tool names are namespaced: server__original_tool_name
    e.g. telegram__send_message, github__create_issue,
         filesystem__read_file, windows__Shell, linkedin__search_jobs
    """

    def __init__(self):
        self._clients: Dict[str, MCPClient] = {}
        # namespaced_name → (client, original_mcp_tool_name)
        self._tool_registry: Dict[str, Tuple[MCPClient, str]] = {}
        self._all_tools: List[dict] = []   # Anthropic-format tool defs
        self._server_defs = _server_definitions()

    async def initialize(self):
        """Spawn MCP servers and discover tools."""
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("MCPCoordinator: starting all MCP servers")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        enabled = [d for d in self._server_defs if d["enabled"]]
        disabled = [d for d in self._server_defs if not d["enabled"]]

        for d in disabled:
            logger.warning(
                f"MCP [{d['name']}]: DISABLED — credentials not configured.\n"
                f"  How to enable: {d['install_hint']}"
            )

        # ─────────────────────────────────────────────
        # START SERVERS
        # telegram must start AFTER all others
        # ─────────────────────────────────────────────

        non_telegram = [d for d in enabled if d["name"] != "telegram"]
        telegram = [d for d in enabled if d["name"] == "telegram"]

        if non_telegram:
            await asyncio.gather(
                *[self._start_server(defn) for defn in non_telegram],
                return_exceptions=True,
            )

        if telegram:
            await self._start_server(telegram[0])

        # ─────────────────────────────────────────────
        # BUILD TOOL REGISTRY
        # ─────────────────────────────────────────────

        self._all_tools = []
        self._tool_registry = {}

        for client in self._clients.values():
            if not client.connected:
                continue

            for tool in client.tools:
                namespaced = tool["name"]
                original = tool["_mcp_name"]

                self._all_tools.append({
                    "name": namespaced,
                    "description": f"[{client.name}] {tool['description']}",
                    "input_schema": tool["input_schema"],
                })

                self._tool_registry[namespaced] = (client, original)

        connected_count = sum(1 for c in self._clients.values() if c.connected)

        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(
            f"MCPCoordinator READY: {connected_count}/{len(self._server_defs)} servers, "
            f"{len(self._all_tools)} tools available"
        )
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    async def _start_server(self, defn: dict):
        """Spawn one MCP server subprocess and fetch its tool list."""
        client = MCPClient(
            name=defn["name"],
            command=defn["command"],
            env=defn["env"],
        )
        self._clients[defn["name"]] = client

        logger.info(f"MCP [{defn['name']}]: spawning → {' '.join(defn['command'][:4])}...")
        ok = await client.start(timeout=defn.get("timeout", 60))


        if ok:
            tools = await client.list_tools()
            expected = defn.get("expected_tools", [])
            got = {t["_mcp_name"] for t in tools}
            logger.info(
                f"MCP [{defn['name']}]: {len(tools)} tools discovered "
                f"(expected ~{len(expected)})"
            )
            # Warn about any expected tools that didn't show up
            missing = set(expected) - got
            if missing:
                logger.debug(
                    f"MCP [{defn['name']}]: some expected tools not found: "
                    f"{', '.join(list(missing)[:5])}{'...' if len(missing) > 5 else ''}"
                )
        else:
            logger.error(
                f"MCP [{defn['name']}]: FAILED to start.\n"
                f"  Command: {' '.join(defn['command'])}\n"
                f"  Fix: {defn.get('install_hint', 'see README')}"
            )

    # ── Public Interface ──────────────────────────────────────────────────────

    async def get_tools(self) -> List[dict]:
        """Return all Anthropic-format tool definitions for connected servers."""
        return self._all_tools

    async def get_tool_names(self) -> List[str]:
        """Return all namespaced tool names."""
        return list(self._tool_registry.keys())

    async def execute_tool(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """
        Execute a tool by its namespaced name via JSON-RPC tools/call.

        Args:
            tool_name:  Namespaced name like "telegram__send_message"
            tool_input: Dict of arguments matching the tool's input_schema
        Returns:
            String result from the MCP server
        """
        if tool_name not in self._tool_registry:
            sample = list(self._tool_registry.keys())[:8]
            return (
                f"⚠️ Unknown tool: '{tool_name}'\n"
                f"Sample available tools: {', '.join(sample)}"
            )

        client, original_name = self._tool_registry[tool_name]

        if not client.connected:
            return (
                f"⚠️ MCP server '{client.name}' is not connected.\n"
                f"Check logs for startup errors."
            )

        logger.info(f"🔧 [{client.name}] → {original_name}({str(tool_input)[:80]})")
        result = await client.call_tool(original_name, tool_input)
        logger.debug(f"🔧 [{client.name}] ← {str(result)[:120]}")
        return result

    async def get_status(self) -> Dict[str, dict]:
        """
        Return status of ALL servers (connected + disabled).
        Used by /status command in Telegram.
        """
        status = {}

        # Connected/attempted servers
        for name, client in self._clients.items():
            status[name] = {
                "connected": client.connected,
                "tools": len(client.tools),
                "status": "connected" if client.connected else "failed",
                "sample_tools": [t["_mcp_name"] for t in client.tools[:5]],
            }

        # Disabled servers (never started)
        for defn in self._server_defs:
            if defn["name"] not in status:
                status[defn["name"]] = {
                    "connected": False,
                    "tools": 0,
                    "status": "disabled (no credentials)",
                    "sample_tools": defn.get("expected_tools", [])[:5],
                }

        return status

    async def get_tools_by_server(self, server_name: str) -> List[str]:
        """Return tool names for a specific server (for skill routing)."""
        client = self._clients.get(server_name)
        if not client or not client.connected:
            return []
        return [t["name"] for t in client.tools]  # namespaced names

    async def shutdown(self):
        """Gracefully stop all MCP server subprocesses."""
        logger.info("MCPCoordinator: shutting down...")
        await asyncio.gather(
            *[c.stop() for c in self._clients.values()],
            return_exceptions=True,
        )
        logger.info("MCPCoordinator: all servers stopped")
