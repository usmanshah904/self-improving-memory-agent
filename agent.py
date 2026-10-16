"""Memory-aware, adaptive work assistant.

Each run: retrieve memories relevant to the task -> answer with them (Claude)
-> extract one reusable preference, skill or instruction (Claude) -> save it,
consolidating it with similar memories. The next run starts from what the
previous runs learned.

Claude is reached through the already-authenticated Claude Code CLI
(`claude -p`); no API key is needed.

Usage:
    python agent.py "Explain what an API is"     # one task
    python agent.py                               # asks for the task
    python agent.py --show-memories               # list what it has learned
    python agent.py --consolidate                 # merge similar memories
    python agent.py --reset                       # forget everything
    python agent.py --memory-file demo.json ...   # use a separate memory store
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys

import memory_manager

CLAUDE_TIMEOUT_SECONDS = 180


def ask_claude(prompt: str) -> str:
    """Send a prompt to Claude Code CLI and return its response."""

    claude_path = shutil.which("claude")

    if not claude_path:
        return "ERROR: Claude Code CLI was not found."

    try:
        result = subprocess.run(
            [claude_path, "-p", prompt],
            capture_output=True,
            # The CLI writes UTF-8; without this, Windows decodes it with the
            # legacy code page and characters like "—" come out garbled.
            encoding="utf-8",
            errors="replace",
            timeout=CLAUDE_TIMEOUT_SECONDS,
        )

        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"

        return result.stdout.strip()

    except subprocess.TimeoutExpired:
        return "ERROR: Claude timed out."

    except Exception as error:
        return f"ERROR: {error}"


def generate_response(
    user_task: str,
    relevant_memories: list[dict]
) -> str:
    """Generate a response using relevant memories and learned skills."""

    if relevant_memories:
        memory_text = "\n".join(
            f"- [{memory['category']}] {memory['memory']}"
            for memory in relevant_memories
        )
    else:
        memory_text = "- No relevant memories found."

    prompt = f"""
You are a helpful personal work assistant.

Current user task:
{user_task}

Relevant memories and learned behaviors:
{memory_text}

Instructions:
- Use relevant memories when they are useful.
- If a memory describes a preference, follow that preference.
- If a memory describes a skill or reusable behavior, apply it.
- Adapt your response based on what was learned from previous runs.
- Do not mention the memory system to the user.
- Do not invent facts.
- Give a clear and useful response.

Respond directly to the user's task.
"""

    return ask_claude(prompt)


def parse_learning(reply: str) -> dict | None:
    """Read the learning step's JSON reply.

    Tolerates the reply being wrapped in a ```json code block or surrounded by
    other text: the first {...} object is used.
    """
    match = re.search(r"\{.*\}", reply, flags=re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not data.get("should_remember"):
        return None

    memory = str(data.get("memory", "")).strip()
    category = str(data.get("category", "")).strip()
    if not memory:
        return None
    if category not in memory_manager.CATEGORIES:
        category = "preference"
    return {"memory": memory, "category": category}


def extract_learning(
    user_task: str,
    response: str
) -> dict | None:
    """
    Ask Claude to identify a reusable preference,
    instruction, or skill from the interaction.
    """

    prompt = f"""
You are the learning component of a personal work assistant.

Current user task:
{user_task}

Assistant response:
{response}

Determine whether this interaction contains something genuinely
useful that should be remembered for future interactions.

Look for:

1. A user preference
   Example:
   "The user prefers short explanations."

2. A reusable skill or behavior
   Example:
   "When explaining technical concepts, use simple language
   and provide one practical example."

3. A reusable instruction
   Example:
   "When summarizing reports, use bullet points."

Do NOT save:
- temporary information
- facts that are only relevant to this one task
- the current question itself
- duplicate information that is already covered by an existing memory

If useful learning exists, return ONLY valid JSON:

{{
    "should_remember": true,
    "memory": "short reusable preference, skill, or instruction",
    "category": "skill"
}}

The category must be exactly one of:

- preference
- skill
- instruction

If there is nothing useful to remember, return:

{{
    "should_remember": false,
    "memory": "",
    "category": ""
}}
"""

    result = ask_claude(prompt)
    if result.startswith("ERROR:"):
        print(f"[learning] {result}")
        return None

    learning = parse_learning(result)
    if learning is None and "should_remember" not in result:
        print("[learning] Claude did not return valid JSON.")
    return learning


def run_agent(user_task: str) -> int:
    """Run one complete agent interaction. Returns a process exit code."""

    # ---------------------------------------------------------
    # 1. Retrieve relevant memories
    # ---------------------------------------------------------

    relevant_memories = memory_manager.search_memories(user_task)

    print("\n[retrieval]")

    if relevant_memories:
        print("Relevant memories:")

        for memory in relevant_memories:
            print(
                f"- [{memory['category']}] "
                f"{memory['memory']}"
            )

    else:
        print("No relevant memories found.")

    # ---------------------------------------------------------
    # 2. Generate response using memory
    # ---------------------------------------------------------

    print("\n[agent]")

    response = generate_response(
        user_task,
        relevant_memories
    )

    if response.startswith("ERROR:"):
        print(response)
        return 1

    print(response)
    memory_manager.mark_used([m["id"] for m in relevant_memories])

    # ---------------------------------------------------------
    # 3. Learn reusable behavior
    # ---------------------------------------------------------

    print("\n[learning]")

    learning = extract_learning(
        user_task,
        response
    )

    if learning:
        result = memory_manager.save_memory(
            learning["memory"],
            learning["category"]
        )

        if result["action"] == "consolidated":
            print(f"[memory] Consolidated {result['merged']} similar memory(s).")
        else:
            print("[memory] Added new memory.")

        print(
            f"Learned {learning['category']}:"
        )

        print(
            f"- {learning['memory']}"
        )

    else:
        print("No new reusable learning.")

    print("\n[done]")
    return 0


def show_memories() -> None:
    memories = memory_manager.get_memories()
    if not memories:
        print("No memories saved yet.")
        return
    print(f"{len(memories)} memory(s):")
    for m in memories:
        used = f"used {m['use_count']}x" if m["use_count"] else "not used yet"
        print(f"- [{m['category']}] {m['memory']}  ({used})")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Memory-aware, adaptive work assistant.")
    parser.add_argument("task", nargs="*", help="what you want help with (asked interactively if omitted)")
    parser.add_argument("--show-memories", action="store_true", help="list saved memories and exit")
    parser.add_argument("--consolidate", action="store_true", help="merge similar saved memories and exit")
    parser.add_argument("--reset", action="store_true", help="delete all saved memories and exit")
    parser.add_argument("--memory-file", help="memory store to use (default: memory/memories.json)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.memory_file:
        os.environ["MEMORY_FILE"] = args.memory_file

    if args.show_memories:
        show_memories()
        return 0
    if args.consolidate:
        removed = memory_manager.consolidate()
        print(f"Merged similar memories: {removed} removed.")
        show_memories()
        return 0
    if args.reset:
        removed = memory_manager.clear_memories()
        print(f"Deleted {removed} memory(s).")
        return 0

    print("=" * 60)
    print("MEMORY-AWARE + ADAPTIVE WORK ASSISTANT")
    print("=" * 60)

    user_task = " ".join(args.task).strip()
    if not user_task:
        user_task = input("\nWhat would you like help with?\n> ").strip()
    else:
        print(f"\nTask: {user_task}")

    if not user_task:
        print("No task provided.")
        return 1

    return run_agent(user_task)


if __name__ == "__main__":
    sys.exit(main())
