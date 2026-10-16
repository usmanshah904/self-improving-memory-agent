import json
from pathlib import Path


MEMORY_FILE = Path(__file__).parent / "memory" / "memories.json"


def load_memories() -> list[dict]:
    """Load all saved memories."""

    if not MEMORY_FILE.exists():
        return []

    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, list):
            return []

        return data

    except (json.JSONDecodeError, OSError):
        return []


def save_memory(
    memory: str,
    category: str = "preference"
) -> None:
    """
    Save a memory and consolidate highly similar memories.

    If the new memory is similar to existing memories,
    replace them with the new, more detailed memory.
    """

    memories = load_memories()

    new_words = set(memory.lower().split())

    if not new_words:
        return

    matching_indices = []

    for index, existing in enumerate(memories):
        existing_text = existing.get("memory", "")
        existing_words = set(existing_text.lower().split())

        if not existing_words:
            continue

        common_words = new_words & existing_words

        score = len(common_words) / min(
            len(new_words),
            len(existing_words)
        )

        if score >= 0.6:
            matching_indices.append(index)

    new_memory = {
        "memory": memory,
        "category": category
    }

    if matching_indices:
        # Keep the position of the first matching memory.
        first_index = matching_indices[0]

        # Remove all matching memories, starting from the end
        # so that indexes do not shift incorrectly.
        for index in reversed(matching_indices):
            del memories[index]

        # Insert the new, consolidated memory.
        memories.insert(first_index, new_memory)

        print(
            f"[memory] Consolidated "
            f"{len(matching_indices)} similar memory(s)."
        )

    else:
        memories.append(new_memory)

        print("[memory] Added new memory.")

    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(MEMORY_FILE, "w", encoding="utf-8") as file:
        json.dump(memories, file, indent=2)


def get_memories() -> list[dict]:
    """Return all stored memories."""

    return load_memories()


def search_memories(query: str) -> list[dict]:
    """
    Find memories relevant to the query.

    Memories are ranked by keyword overlap.
    """

    memories = load_memories()

    if not query.strip():
        return []

    query_words = set(query.lower().split())

    relevant = []

    for memory in memories:
        memory_text = memory.get("memory", "").lower()

        score = 0

        for word in query_words:
            if word in memory_text:
                score += 1

        if score > 0:
            relevant.append((score, memory))

    relevant.sort(key=lambda item: item[0], reverse=True)

    return [memory for score, memory in relevant]


if __name__ == "__main__":

    print("BEFORE CONSOLIDATION:")

    for memory in get_memories():
        print(f"- {memory['memory']}")

    print("\nADDING NEW MEMORY...")

    save_memory(
        "User prefers short, beginner-friendly technical explanations with a simple example.",
        "preference"
    )

    print("\nAFTER CONSOLIDATION:")

    for memory in get_memories():
        print(f"- {memory['memory']}")