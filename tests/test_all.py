"""
LocalMind Test Suite
Tests for all major components:
  - Memory store
  - RAG retriever
  - Skill executor
  - MCP coordinator
  - Full pipeline integration

Runnable both with pytest (`pytest`) and directly (`python tests/test_all.py`).
"""

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Set dummy env vars for testing
os.environ.setdefault("LLM_BASE_URL", "http://localhost:11434/v1")
os.environ.setdefault("LLM_MODEL", "kimi-k2.5:cloud")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token")


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ══════════════════════════════════════════════════════════════
# Test 1: Memory Store
# ══════════════════════════════════════════════════════════════
def test_memory_store():
    print("\n🧪 Testing Memory Store...")
    from memory_store.memory import MemoryStore

    with tempfile.TemporaryDirectory() as tmpdir:
        mem = MemoryStore(tmpdir)
        run(mem.initialize())

        # Test soul
        soul = run(mem.get_soul())
        assert "LocalMind" in soul or len(soul) > 10, "SOUL.md empty"
        print("  ✅ SOUL.md loaded")

        # Test user prefs
        run(mem.set_user_prefs(12345, "User prefers concise responses."))
        prefs = run(mem.get_user_prefs(12345))
        assert "concise" in prefs
        print("  ✅ User preferences saved/loaded")

        # Test memory facts
        run(mem.save_memory_fact(12345, "User is a Python developer"))
        facts = run(mem.get_memory_facts(12345))
        assert "Python" in facts
        print("  ✅ Memory facts saved/loaded")

        # Test conversation history
        run(mem.add_turn(12345, "Hello bot", "Hello user!"))
        run(mem.add_turn(12345, "How are you?", "I'm doing great!"))
        hist = run(mem.get_history(12345))
        assert len(hist) == 4  # 2 turns × 2 messages
        assert hist[0]["content"] == "Hello bot"
        print("  ✅ Conversation history works")

        # Test clear
        run(mem.clear_history(12345))
        hist = run(mem.get_history(12345))
        assert len(hist) == 0
        print("  ✅ History cleared")

    return


# ══════════════════════════════════════════════════════════════
# Test 3: RAG Retriever
# ══════════════════════════════════════════════════════════════
def test_rag_retriever():
    print("\n🧪 Testing RAG Retriever...")

    try:
        import chromadb  # noqa: F401
        from sentence_transformers import SentenceTransformer  # noqa: F401
    except ImportError:
        print("  ⚠️ chromadb/sentence-transformers not installed, skipping RAG test")
        return

    from rag.retriever import RAGRetriever

    with tempfile.TemporaryDirectory() as tmpdir:
        rag = RAGRetriever(
            persist_dir=tmpdir,
            embedding_model="all-MiniLM-L6-v2",
            top_k=3,
            min_score=0.1,
        )
        run(rag.initialize())

        # Index test documents
        docs = [
            ("We decided to use ChromaDB for vector storage on 2026-01-15.", "decision_1"),
            ("The project uses Python 3.11 and runs on Ubuntu.", "decision_2"),
            ("API keys should never be committed to git.", "security_note"),
            ("The Telegram bot uses python-telegram-bot library.", "tech_note"),
            ("LocalMind was built in March 2026 by Yogi.", "about"),
        ]

        total = 0
        for text, doc_id in docs:
            n = run(rag.index_text(text, doc_id))
            total += n
        print(f"  ✅ Indexed {total} chunks")

        # Test retrieval
        results = run(rag.retrieve("What database is used for vectors?"))
        print(f"  ✅ Retrieved {len(results)} results for vector DB query")
        if results:
            print(f"    Top result (score={results[0]['score']:.2f}): {results[0]['text'][:60]}")
            assert "ChromaDB" in results[0]["text"], "Expected ChromaDB in top result"

        results2 = run(rag.retrieve("Who built LocalMind?"))
        print(f"  ✅ Retrieved {len(results2)} results for creator query")

        # Test chunking
        long_text = "Lorem ipsum. " * 100
        chunks = rag._chunk_text(long_text)
        assert len(chunks) > 1, "Long text should be chunked"
        print(f"  ✅ Chunking works ({len(chunks)} chunks from long text)")

        stats = run(rag.get_stats())
        print(f"  ✅ Stats: {stats}")

    return


# ══════════════════════════════════════════════════════════════
# Test 4: Skill Executor
# ══════════════════════════════════════════════════════════════
def test_skill_executor():
    print("\n🧪 Testing Skill Executor...")
    from skills.executor import SkillExecutor

    with tempfile.TemporaryDirectory() as tmpdir:
        exec_ = SkillExecutor(tmpdir)
        run(exec_.initialize())

        # Check default skills loaded
        skills = run(exec_.list_skills())
        assert len(skills) > 0, "No skills loaded"
        names = [s["name"] for s in skills]
        print(f"  ✅ Loaded {len(skills)} skills: {', '.join(names)}")

        # Check triggers
        triggers = run(exec_.get_triggers())
        assert "summarize" in triggers
        print(f"  ✅ Skill triggers loaded for: {', '.join(triggers.keys())}")

        # Test skill prompt building
        skill = exec_.skills.get("summarize")
        assert skill is not None
        prompt = skill.build_prompt("This is a test message")
        assert "test message" in prompt
        print("  ✅ Skill prompt template renders correctly")

    return


# ══════════════════════════════════════════════════════════════
# Test 5: MCP Coordinator
# ══════════════════════════════════════════════════════════════
def test_mcp_coordinator():
    print("\n🧪 Testing MCP Coordinator...")
    from mcp.coordinator import MCPCoordinator

    coord = MCPCoordinator()
    run(coord.initialize())

    status = run(coord.get_status())
    print("  MCP Server Status:")
    for name, info in status.items():
        icon = "✅" if info["connected"] else "⚠️"
        print(f"    {icon} {name}: {info['status']} ({info['tools']} tools)")

    tool_names = run(coord.get_tool_names())
    print(f"  ✅ Total available tools: {len(tool_names)}")

    # Test the filesystem tool if the server actually connected (needs Node.js
    # / npx). Tools are namespaced as "<server>__<tool>", so it's
    # "filesystem__read_file", not "fs_read_file".
    if "filesystem__read_file" not in tool_names:
        print("  ⚠️ filesystem MCP server not connected (Node.js/npx missing?) — skipping tool call test")
        return

    import tempfile
    home_dir = os.path.expanduser("~")
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, dir=home_dir
    ) as f:
        f.write("Test content for LocalMind")
        test_file = f.name

    result = run(coord.execute_tool("filesystem__read_file", {"path": test_file}))
    assert "Test content" in result, f"Expected file content, got: {result}"
    print(f"  ✅ Filesystem tool works: read {len(result)} chars")

    os.unlink(test_file)
    return


# ══════════════════════════════════════════════════════════════
# Test 6: Full Architecture Validation
# ══════════════════════════════════════════════════════════════
def test_architecture():
    print("\n🧪 Testing Architecture Imports...")
    modules = [
        "config.settings",
        "engine.router",
        "memory_store.memory",
        "rag.retriever",
        "mcp.coordinator",
        "skills.executor",
        "skills.tool_registry",
        "telegram_handler.handler",
    ]
    failures = []
    for mod in modules:
        try:
            __import__(mod)
            print(f"  ✅ {mod}")
        except Exception as e:  # noqa: BLE001 - test wants the message
            print(f"  ❌ {mod}: {e}")
            failures.append(f"{mod}: {e}")

    assert not failures, f"Import failures: {failures}"
    return


# ══════════════════════════════════════════════════════════════
# Run All Tests
# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  LocalMind Test Suite")
    print("=" * 60)

    results = {}

    try:
        test_architecture()
        results["architecture"] = "PASS"
    except Exception as e:
        results["architecture"] = f"FAIL: {e}"

    try:
        test_memory_store()
        results["memory_store"] = "PASS"
    except Exception as e:
        results["memory_store"] = f"FAIL: {e}"

    try:
        test_rag_retriever()
        results["rag_retriever"] = "PASS"
    except Exception as e:
        results["rag_retriever"] = f"FAIL: {e}"

    try:
        test_skill_executor()
        results["skill_executor"] = "PASS"
    except Exception as e:
        results["skill_executor"] = f"FAIL: {e}"

    try:
        test_mcp_coordinator()
        results["mcp_coordinator"] = "PASS"
    except Exception as e:
        results["mcp_coordinator"] = f"FAIL: {e}"

    print("\n" + "=" * 60)
    print("  Test Results Summary")
    print("=" * 60)
    for name, result in results.items():
        icon = "✅" if result == "PASS" else "❌"
        print(f"  {icon} {name}: {result}")

    failed = sum(1 for r in results.values() if r != "PASS")
    print(f"\n  {len(results) - failed}/{len(results)} tests passed")
    print("=" * 60)
