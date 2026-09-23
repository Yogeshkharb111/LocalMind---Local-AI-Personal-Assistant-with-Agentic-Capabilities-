"""
LocalMind Real MCP Client
Communicates with MCP servers via JSON-RPC 2.0 over stdio.
Uses threading for subprocess IO to avoid Windows ProactorEventLoop bugs.
"""

import asyncio
import json
import os
import queue
import subprocess
import threading
from typing import Any

from loguru import logger


class MCPClient:
    """
    A single MCP server connection via subprocess + JSON-RPC stdio.
    Uses a background thread to read stdout, avoiding Windows asyncio subprocess bugs.
    """

    def __init__(self, name: str, command: list[str], env: dict[str, str] | None = None):
        self.name = name
        self.command = command
        self.env = env or {}
        self._process: subprocess.Popen | None = None
        self._request_id = 0
        self.tools: list[dict] = []
        self.connected = False
        self._read_queue: queue.Queue = queue.Queue()
        self._reader_thread: threading.Thread | None = None
        self._write_lock = threading.Lock()

    def _reader_loop(self):
        """Background thread: reads lines from subprocess stdout and puts them in queue."""
        try:
            while self._process and self._process.stdout:
                line = self._process.stdout.readline()
                if not line:
                    break
                try:
                    obj = json.loads(line.decode().strip())
                    self._read_queue.put(obj)
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass

    def _stderr_drain_loop(self):
        """Background thread: drains stderr and logs it for debugging."""
        try:
            while self._process and self._process.stderr:
                line = self._process.stderr.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text:
                    logger.debug(f"MCP [{self.name}] stderr: {text}")
        except Exception:
            pass

    def _write(self, obj: dict):
        """Write a JSON-RPC message to subprocess stdin."""
        line = json.dumps(obj) + "\n"
        with self._write_lock:
            self._process.stdin.write(line.encode())
            self._process.stdin.flush()

    async def _send_request(self, method: str, params: dict, timeout: float = 30.0) -> dict | None:
        """Send JSON-RPC request, wait for matching response using thread queue."""
        self._request_id += 1
        req_id = self._request_id

        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._write, request)

        deadline = loop.time() + timeout
        while loop.time() < deadline:
            remaining = deadline - loop.time()
            try:
                # Use executor to do blocking queue.get without blocking event loop
                response = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda r=remaining: self._read_queue.get(timeout=min(1.0, r)),
                    ),
                    timeout=min(2.0, remaining + 0.5),
                )
            except (TimeoutError, queue.Empty):
                if loop.time() >= deadline:
                    raise TimeoutError(f"Timeout waiting for response to {method}") from None
                continue

            if response is None:
                continue
            if "id" not in response:
                continue  # skip notifications
            if response.get("id") == req_id:
                if "error" in response:
                    logger.warning(f"MCP [{self.name}] RPC error: {response['error']}")
                    return None
                return response.get("result")

        raise TimeoutError(f"No response matched id={req_id} for {method}")

    async def _send_notification(self, method: str, params: dict = None):
        """Send a JSON-RPC notification (no response expected)."""
        notification = {"jsonrpc": "2.0", "method": method}
        if params:
            notification["params"] = params
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._write, notification)

    async def start(self, timeout: float = 30.0) -> bool:
        """Spawn subprocess and perform MCP initialize handshake."""
        try:
            merged_env = {**os.environ, **self.env}

            # Use synchronous subprocess.Popen — no asyncio subprocess bugs
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,  # capture stderr for debugging
                env=merged_env,
            )

            # Start background reader thread for stdout
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                daemon=True,
                name=f"mcp-reader-{self.name}"
            )
            self._reader_thread.start()

            # Start background stderr drain thread
            threading.Thread(
                target=self._stderr_drain_loop,
                daemon=True,
                name=f"mcp-stderr-{self.name}"
            ).start()

            # MCP initialize handshake
            init_result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "localmind", "version": "2.0.0"},
            }, timeout=timeout)

            if init_result is None:
                logger.warning(f"MCP [{self.name}]: initialize returned None")
                return False

            await self._send_notification("notifications/initialized")

            self.connected = True
            server_info = init_result.get("serverInfo", {})
            logger.info(
                f"MCP [{self.name}]: connected ✅ "
                f"(server={server_info.get('name','?')} v{server_info.get('version','?')})"
            )
            return True

        except FileNotFoundError:
            logger.warning(f"MCP [{self.name}]: command not found: {self.command[0]}")
            return False
        except TimeoutError:
            logger.warning(f"MCP [{self.name}]: connection timed out")
            return False
        except Exception as e:
            logger.warning(f"MCP [{self.name}]: failed to start: {e}")
            return False

    async def list_tools(self) -> list[dict]:
        """Fetch all tools via tools/list."""
        if not self.connected:
            return []
        try:
            result = await self._send_request("tools/list", {}, timeout=30.0)
            if not result:
                return []

            raw_tools = result.get("tools", [])
            openai_tools = []
            for tool in raw_tools:
                openai_tools.append({
                    "name": f"{self.name}__{tool['name']}",
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("inputSchema", {"type": "object", "properties": {}}),
                    "_mcp_name": tool["name"],
                    "_mcp_server": self.name,
                })

            self.tools = openai_tools
            logger.info(f"MCP [{self.name}]: discovered {len(openai_tools)} tools")
            return openai_tools

        except Exception as e:
            logger.error(f"MCP [{self.name}]: tools/list failed: {e}")
            return []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Execute a tool via tools/call."""
        if not self.connected:
            return f"Error: MCP server '{self.name}' is not connected."
        try:
            result = await self._send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            }, timeout=60.0)

            if result is None:
                return f"Error: No response from '{self.name}' for tool '{tool_name}'"

            content = result.get("content", [])
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif block.get("type") == "image":
                            parts.append(f"[Image: {block.get('mimeType', 'image')}]")
                        elif block.get("type") == "resource":
                            parts.append(str(block.get("resource", "")))
                    else:
                        parts.append(str(block))
                return "\n".join(parts) or "(empty response)"
            elif isinstance(content, str):
                return content

            return json.dumps(result, indent=2)

        except TimeoutError:
            return f"Error: Tool '{tool_name}' timed out after 60s"
        except Exception as e:
            logger.error(f"MCP [{self.name}]: tools/call '{tool_name}' failed: {e}")
            return f"Error executing '{tool_name}': {str(e)}"

    async def stop(self):
        """Terminate the subprocess."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            self._process = None
            self.connected = False
            logger.info(f"MCP [{self.name}]: stopped")
