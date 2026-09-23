# engine/ — LLM-First Router

The brain. Router runs the three-stage Plan -> Execute -> Respond loop for every message. The model plans, calls tools in a loop, then writes the final answer. intent_classifier.py is a legacy component and is not in the active path.

## Files

| File | Responsibility |
|------|----------------|
| `__init__.py` | Marks the package. |
| `router.py` | Router: _plan(), _execute() (agentic tool loop up to 15 iterations), _respond(); persists each turn. |
| `intent_classifier.py` | Legacy rule/LLM intent tagging. Kept for reference; unused by the LLM-first router. |

## Flow

```mermaid
flowchart LR
    M["user message"] --> P["STAGE 1: PLAN"]
    P --> E["STAGE 2: EXECUTE (tool loop)"]
    E --> RS["STAGE 3: RESPOND"]
    RS --> SV["save turn + daily log"]
    E -.calls.-> TR["ToolRegistry"]
```

## Example

```python
router = Router(memory, rag, mcp_coordinator, skill_executor)
reply = await router.process(user_id, user_name, "summarize my notes")
```

---
_Part of [LocalMind](../README.md). See [docs/architecture.html](architecture.html) for the full interactive architecture and sequence diagrams._
