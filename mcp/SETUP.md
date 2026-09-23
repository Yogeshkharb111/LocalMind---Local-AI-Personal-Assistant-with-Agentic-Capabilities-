# MCP Server Setup Guide
# Exact commands from each repo's README

## How LocalMind uses MCP servers

LocalMind spawns each MCP server as a real subprocess and talks to it via
JSON-RPC 2.0 over stdio. Tools are discovered dynamically via `tools/list`
so you get ALL tools from each server automatically.

```
LocalMind (MCPCoordinator)
    │
    ├── subprocess: uv --directory /path/to/telegram-mcp run main.py /tmp
    │     ← JSON-RPC stdio → 63 Telegram tools
    │
    ├── subprocess: uvx github-mcp-server stdio
    │     ← JSON-RPC stdio → ~28 GitHub tools
    │
    ├── subprocess: npx -y @modelcontextprotocol/server-filesystem ~ /tmp
    │     ← JSON-RPC stdio → 8 filesystem tools
    │
    ├── subprocess: uvx windows-mcp          (Windows only)
    │     ← JSON-RPC stdio → 16 Windows tools
    │
    └── subprocess: uvx linkedin-mcp-server
          ← JSON-RPC stdio → 5 LinkedIn tools
```

---

## Prerequisites

```bash
pip install uv        # needed for uvx
node --version        # Node.js needed for filesystem MCP (https://nodejs.org)
```

---

## Server 1: Telegram MCP (63 tools)
Source: https://github.com/chigwell/telegram-mcp

### Install
```bash
# Option A: Clone (RECOMMENDED — gives file tools like send_file, download_media)
git clone https://github.com/chigwell/telegram-mcp.git
cd telegram-mcp
uv sync
uv run session_string_generator.py   # generates your session string

# Option B: Install via pip (no file tools, but simpler)
pip install telegram-mcp
```

### Configure .env
```
TELEGRAM_API_ID=your_api_id          # from my.telegram.org/apps
TELEGRAM_API_HASH=your_api_hash      # from my.telegram.org/apps
TELEGRAM_SESSION_STRING=your_string  # from session_string_generator.py

# Required if you used Option A (clone):
TELEGRAM_MCP_DIR=/full/path/to/telegram-mcp

# Required for file tools (send_file, download_media, send_voice, etc.):
TELEGRAM_MCP_FILE_ROOTS=/home/youruser/telegram-files /tmp
```

### How LocalMind launches it
```bash
# If TELEGRAM_MCP_DIR is set (Option A):
uv --directory /path/to/telegram-mcp run main.py /home/user/telegram-files /tmp

# If using pip install (Option B):
uvx telegram-mcp /home/user/telegram-files /tmp
```

### All 63 tools you get
Chat & Group: get_chats, list_chats, get_chat, create_group, invite_to_group,
  create_channel, edit_chat_title, delete_chat_photo, leave_chat,
  get_participants, get_admins, get_banned_users, promote_admin, demote_admin,
  ban_user, unban_user, get_invite_link, export_chat_invite, import_chat_invite,
  join_chat_by_link, subscribe_public_channel

Messaging: get_messages, list_messages, list_topics, send_message,
  reply_to_message, edit_message, delete_message, forward_message,
  pin_message, unpin_message, mark_as_read, get_message_context, get_history,
  get_pinned_messages, get_last_interaction, create_poll, list_inline_buttons,
  press_inline_button, send_reaction, remove_reaction, get_message_reactions

Contacts: list_contacts, search_contacts, add_contact, delete_contact,
  block_user, unblock_user, import_contacts, export_contacts,
  get_blocked_users, get_contact_ids, get_direct_chat_by_contact, get_contact_chats

User/Profile: get_me, update_profile, delete_profile_photo,
  get_user_photos, get_user_status

Media (requires TELEGRAM_MCP_FILE_ROOTS): send_file, download_media,
  set_profile_photo, edit_chat_photo, send_voice, send_sticker,
  upload_file, get_media_info

Search: search_public_chats, search_messages, resolve_username

Bots: get_sticker_sets, get_bot_info, set_bot_commands

Privacy: get_privacy_settings, set_privacy_settings, mute_chat,
  unmute_chat, archive_chat, unarchive_chat, get_recent_actions

Drafts: save_draft, get_drafts, clear_draft

---

## Server 2: GitHub MCP (~28 tools)
Source: https://github.com/github/github-mcp-server

### Install
```bash
# No install needed — uvx downloads it automatically
```

### Configure .env
```
GITHUB_TOKEN=ghp_your_personal_access_token
```
Create token at: https://github.com/settings/tokens
Scopes needed: repo, read:org

### How LocalMind launches it
```bash
uvx github-mcp-server stdio
```

---

## Server 3: Filesystem MCP (8 tools)
Source: https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem

### Install
```bash
# Requires Node.js: https://nodejs.org
# npx auto-installs it on first run — nothing to do
```

### No credentials needed

### How LocalMind launches it
```bash
npx -y @modelcontextprotocol/server-filesystem ~ /tmp
```

### Tools
read_file, write_file, list_directory, search_files,
create_directory, move_file, get_file_info, list_allowed_directories

---

## Server 4: Windows MCP (16 tools) — Windows only
Source: https://github.com/CursorTouch/Windows-MCP
PyPI: windows-mcp

### Install
```bash
pip install uv   # for uvx
# uvx handles the rest automatically
```

### No credentials needed. Auto-enabled on Windows.

### How LocalMind launches it
```bash
uvx windows-mcp
```

### Tools (exact names from README)
Click, Type, Scroll, Move, Shortcut, Wait, Snapshot,
App, Shell, Scrape, MultiSelect, MultiEdit,
Clipboard, Process, Notification, Registry

Note: Snapshot supports use_dom=True for browser automation
      and use_vision=True for screenshot inclusion.

---

## Server 5: LinkedIn MCP (5 tools)
Source: https://github.com/stickerdaniel/linkedin-mcp-server

### Configure .env
```
LINKEDIN_EMAIL=your@email.com
LINKEDIN_PASSWORD=yourpassword
```

### How LocalMind launches it
```bash
uvx linkedin-mcp-server
```

### Tools
get_profile, search_jobs, search_people, get_company, get_job_details

---

## Verify everything works

Start LocalMind and send `/status` in Telegram:

```
📊 LocalMind Status

MCP Servers:
✅ telegram:    connected (63 tools)
✅ github:      connected (28 tools)
✅ filesystem:  connected (8 tools)
⚠️ windows:     disabled (Linux/macOS)
✅ linkedin:    connected (5 tools)

Total: 104 tools available
```
