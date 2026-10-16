import json
import shutil
import subprocess

from memory_manager import search_memories, save_memory


def ask_claude(prompt: str) -> str:
    """Send a prompt to Claude Code CLI and return its response."""

    claude_path = shutil.which("claude")

    if not claude_path:
        return "ERROR: Claude Code CLI was not found."

    try:
        result = subprocess.run(
            [claude_path, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=180,
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

    try:
        data = json.loads(result)

        if not data.get("should_remember"):
            return None

        memory = data.get("memory", "").strip()
        category = data.get("category", "").strip()

        if not memory:
            return None

        if category not in {
            "preference",
            "skill",
            "instruction"
        }:
            category = "preference"

        return {
            "memory": memory,
            "category": category,
        }

    except json.JSONDecodeError:
        print("[learning] Claude did not return valid JSON.")
        return None


def run_agent() -> None:
    """Run one complete agent interaction."""

    print("=" * 60)
    print("MEMORY-AWARE + ADAPTIVE WORK ASSISTANT")
    print("=" * 60)

    user_task = input(
        "\nWhat would you like help with?\n> "
    ).strip()

    if not user_task:
        print("No task provided.")
        return

    # ---------------------------------------------------------
    # 1. Retrieve relevant memories
    # ---------------------------------------------------------

    relevant_memories = search_memories(user_task)

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
        return

    print(response)

    # ---------------------------------------------------------
    # 3. Learn reusable behavior
    # ---------------------------------------------------------

    print("\n[learning]")

    learning = extract_learning(
        user_task,
        response
    )

    if learning:

        save_memory(
            learning["memory"],
            learning["category"]
        )

        print(
            f"Learned {learning['category']}:"
        )

        print(
            f"- {learning['memory']}"
        )

    else:
        print("No new reusable learning.")

    print("\n[done]")


if __name__ == "__main__":
    run_agent()