"""
LocalMind Router — LLM-First Architecture
========================================
Every message goes through 3 LLM stages:

  STAGE 1 — PLANNER
    LLM reads the message and makes a step-by-step plan.
    Decides which tools/memory it needs. No tools called yet.

  STAGE 2 — EXECUTOR
    LLM executes the plan step by step.
    Calls tools in a loop until task is complete (max 15 iterations).

  STAGE 3 — RESPONDER
    LLM reflects on all results and writes the final response to the user.
    Clean, natural language — no raw tool output.

No intent classifier. No routing rules. LLM decides everything.
"""

import json
from datetime import datetime
from pathlib import Path

import httpx
from loguru import logger
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import settings
from skills.tool_registry import ToolRegistry

# Cap on how much of a single tool result is fed back to the LLM, to bound
# context size and reduce the prompt-injection surface from large tool output.
MAX_TOOL_RESULT_CHARS = 6000


class Router:
    def __init__(self, memory, rag, mcp_coordinator, skill_executor):
        self.memory = memory
        self.rag = rag
        self.mcp_coordinator = mcp_coordinator
        self.skill_executor = skill_executor

        self.llm_base_url = settings.LLM_BASE_URL
        self.llm_api_key  = settings.LLM_API_KEY
        self.llm_model    = settings.LLM_MODEL

        # One shared HTTP client (connection pooling) instead of one per call.
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(120.0))

        self.tool_registry = ToolRegistry(
            mcp_coordinator=mcp_coordinator,
            skill_executor=skill_executor,
            memory=memory,
            rag=rag,
            daily_logs_dir=settings.DAILY_LOGS_DIR,
        )

        logger.info(f"Router initialized | LLM={self.llm_model} @ {self.llm_base_url} | mode=llm-first")

    async def aclose(self):
        """Close the shared HTTP client. Call on shutdown."""
        await self._http.aclose()

    # ── Shared LLM call (pooled client + retry with backoff) ───────────────────
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(
            (httpx.TransportError, httpx.TimeoutException)
        ),
    )
    async def _chat(self, payload: dict, timeout: float = 120.0) -> dict:
        """POST to the OpenAI-compatible /chat/completions endpoint.

        Retries only on transient network/timeout errors (not on HTTP 4xx/5xx),
        so a single blip does not fail the whole turn.
        """
        response = await self._http.post(
            f"{self.llm_base_url}/chat/completions",
            headers=settings.llm_headers(self.llm_api_key),
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    # ── Main Entry Point ──────────────────────────────────────────────────────
    async def process(self, user_id: int, user_name: str, message: str) -> str:
        logger.info(f"Router.process | user={user_id} | msg={message[:80]}")

        soul = await self.memory.get_soul()
        all_tools = await self.tool_registry.get_all_tools()
        tool_names = [t["function"]["name"] for t in all_tools]

        # STAGE 1: PLAN
        plan = await self._plan(soul=soul, message=message, tool_names=tool_names)
        logger.info(f"Plan: {plan[:200]}")

        # STAGE 2: EXECUTE
        execution_results = await self._execute(
            soul=soul, message=message, plan=plan,
            tools=all_tools, user_id=user_id,
        )

        # STAGE 3: RESPOND
        response = await self._respond(
            soul=soul, message=message,
            plan=plan, execution_results=execution_results,
        )

        await self._save_turn(user_id, user_name, message, response)
        return response

    # ── STAGE 1: PLANNER ─────────────────────────────────────────────────────
    async def _plan(self, soul: str, message: str, tool_names: list) -> str:
        tool_list_str = "\n".join(f"  - {t}" for t in tool_names)

        system_prompt = f"""{soul}

You are in PLANNING MODE. Create a concise step-by-step plan to handle the user's request.

Available tools:
{tool_list_str}

Rules:
- Decide upfront: do you need memory? history? knowledge search? which tools?
- If this is simple conversation needing no tools, say: "PLAN: Direct response, no tools needed."
- Be specific about the order of steps. Max 5 steps.

Output format:
PLAN:
1. [step one]
2. [step two]
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Create a plan to handle: {message}"},
        ]

        try:
            data = await self._chat(
                {"model": self.llm_model, "messages": messages, "max_tokens": 512, "temperature": 0.3},
                timeout=60,
            )
            return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"Planner failed: {e}")
            return "PLAN: Direct response using available tools as needed."

    # ── STAGE 2: EXECUTOR ────────────────────────────────────────────────────
    async def _execute(self, soul: str, message: str, plan: str, tools: list, user_id: int) -> list:
        system_prompt = f"""{soul}

You are in EXECUTION MODE. Execute the following plan step by step.
Call tools as needed. Collect all information required for a great response.

Plan:
{plan}

Rules:
- Call tools in the planned order
- If a tool fails, note it and continue
- Do NOT write the final response yet — just execute and collect results
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]

        execution_log = []

        for iteration in range(15):
            logger.debug(f"Executor iteration {iteration + 1}/15")
            try:
                data = await self._chat({
                    "model": self.llm_model,
                    "messages": messages,
                    "max_tokens": 2048,
                    "temperature": 0.3,
                    "tools": tools,
                    "tool_choice": "auto",
                })
            except httpx.ConnectError:
                return [{"tool": "error", "result": "Cannot reach the LLM backend. Is OpenRouter/Ollama reachable?"}]
            except Exception as e:
                logger.exception(f"Executor LLM call failed: {e}")
                return execution_log

            choice = data["choices"][0]
            assistant_msg = choice["message"]
            finish_reason = choice.get("finish_reason", "stop")

            if finish_reason == "tool_calls" and assistant_msg.get("tool_calls"):
                messages.append(assistant_msg)
                for tool_call in assistant_msg["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    try:
                        tool_args = json.loads(tool_call["function"]["arguments"])
                    except json.JSONDecodeError:
                        tool_args = {}

                    logger.info(f"🔧 Tool: {tool_name} | args={str(tool_args)[:120]}")
                    result = await self.tool_registry.execute(
                        tool_name=tool_name, tool_args=tool_args,
                        user_id=user_id, router=self,
                    )
                    logger.debug(f"🔧 Result: {str(result)[:120]}")

                    # Cap the result fed back into the model's context.
                    result_str = str(result)
                    if len(result_str) > MAX_TOOL_RESULT_CHARS:
                        result_str = result_str[:MAX_TOOL_RESULT_CHARS] + "\n…(truncated)"

                    execution_log.append({"tool": tool_name, "args": tool_args, "result": result_str})
                    messages.append({"role": "tool", "tool_call_id": tool_call["id"], "content": result_str})
            else:
                logger.debug(f"Executor complete after {iteration + 1} iteration(s)")
                if assistant_msg.get("content"):
                    execution_log.append({"tool": "__llm_note__", "args": {}, "result": assistant_msg["content"]})
                break

        return execution_log

    # ── STAGE 3: RESPONDER ───────────────────────────────────────────────────
    async def _respond(self, soul: str, message: str, plan: str, execution_results: list) -> str:
        if execution_results:
            results_str = ""
            for entry in execution_results:
                if entry["tool"] == "__llm_note__":
                    results_str += f"\nNote: {entry['result']}\n"
                elif entry["tool"] == "error":
                    results_str += f"\nError: {entry['result']}\n"
                else:
                    results_str += f"\n[{entry['tool']}] → {entry['result'][:800]}\n"
        else:
            results_str = "No tools were called — answer from your own knowledge."

        system_prompt = f"""{soul}

You are in RESPONSE MODE. Write the final response to the user based on execution results.

Rules:
- Be natural, clear, and helpful
- Synthesize tool output into clean readable response
- Don't mention "the plan" or "execution stages" — just respond naturally
- Match tone to the user's message
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": f"Original request: {message}\n\nExecution results:\n{results_str}\n\nWrite the final response.",
            },
        ]

        try:
            data = await self._chat(
                {"model": self.llm_model, "messages": messages, "max_tokens": 2048, "temperature": 0.7}
            )
            return data["choices"][0]["message"]["content"].strip()
        except httpx.ConnectError:
            return "⚠️ Cannot reach the LLM backend. Check LLM_BASE_URL (OpenRouter/Ollama)."
        except Exception as e:
            logger.exception(f"Responder failed: {e}")
            if execution_results:
                last = execution_results[-1]
                return last["result"]
            return f"⚠️ Error: {str(e)}"

    # ── Helpers ───────────────────────────────────────────────────────────────
    async def _save_turn(self, user_id: int, user_name: str, message: str, response: str):
        await self.memory.add_turn(user_id, message, response)
        await self._append_daily_log(user_name, message, response)

    async def _append_daily_log(self, user_name: str, message: str, response: str):
        log_path = Path(settings.DAILY_LOGS_DIR) / f"{datetime.now().strftime('%Y-%m-%d')}.md"
        ts = datetime.now().strftime("%H:%M:%S")
        entry = (
            f"\n### [{ts}]\n"
            f"**{user_name}:** {message}\n\n"
            f"**Bot:** {response[:500]}{'...' if len(response) > 500 else ''}\n"
        )
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(entry)

    # ── Prompt-only helper (used by YAML prompt skills) ───────────────────────
    async def _build_context(self, user_id: int, include_rag=False, rag_context="", include_tools=False) -> dict:
        soul = await self.memory.get_soul()
        history = await self.memory.get_history(user_id, max_turns=settings.MAX_CONVERSATION_HISTORY)
        system = soul
        if rag_context:
            system += f"\n\n## Retrieved Knowledge\n{rag_context}"
        return {"system": system, "history": history}

    async def _call_llm(self, system: str, history: list, message: str) -> str:
        messages = [{"role": "system", "content": system}] + history + [{"role": "user", "content": message}]
        try:
            data = await self._chat(
                {"model": self.llm_model, "messages": messages, "max_tokens": 2048, "temperature": 0.7}
            )
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.exception(f"LLM call failed: {e}")
            return f"⚠️ LLM error: {str(e)}"
