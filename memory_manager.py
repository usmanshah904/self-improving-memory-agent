"""Persistent memory for the assistant: a small JSON store of reusable
preferences, skills and instructions, with relevance search and consolidation.

Matching is deliberately lightweight (no embeddings or extra dependencies):
words are lower-cased, common filler words are dropped, and each remaining
word is reduced to a short stem so that "explain" and "explanations" count as
the same idea. Relevance and similarity are measured on those keywords.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Override with the MEMORY_FILE environment variable (used by tests and demos).
DEFAULT_MEMORY_FILE = Path(__file__).parent / "memory" / "memories.json"

CATEGORIES = {"preference", "skill", "instruction"}

# Memories are relevant when they cover at least this share of the task's keywords.
MIN_RELEVANCE = 0.2
# Two memories are "the same idea" when they share at least MIN_SHARED keywords
# and those make up at least MERGE_SIMILARITY of the shorter memory.
MERGE_SIMILARITY = 0.5
MIN_SHARED = 3

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "then", "so", "to", "of", "in", "on", "at",
    "for", "with", "by", "from", "as", "into", "about", "over", "after", "before", "is",
    "are", "was", "were", "be", "been", "being", "am", "do", "does", "did", "have", "has",
    "had", "i", "me", "my", "we", "our", "you", "your", "he", "she", "it", "its", "they",
    "them", "their", "this", "that", "these", "those", "what", "which", "who", "whom",
    "how", "when", "where", "why", "can", "could", "would", "should", "will", "shall",
    "may", "might", "must", "please", "some", "any", "all", "each", "every", "one",
    "very", "just", "also", "not", "no", "yes", "there", "here", "than", "too", "up",
    "out", "user", "users", "prefers", "prefer", "like", "likes", "want", "wants",
    "give", "giving", "make", "use", "using", "always", "keep", "them",
}

_SUFFIXES = ("ations", "ation", "ings", "ing", "ions", "ion", "ers", "er", "ies", "es", "s", "ed", "ly")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def memory_file() -> Path:
    return Path(os.environ.get("MEMORY_FILE", DEFAULT_MEMORY_FILE))


def _stem(word: str) -> str:
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[: -len(suffix)]
            break
    # A 5-letter prefix is enough to group a word family ("explain", "explanation").
    return word[:5]


def keywords(text: str) -> set[str]:
    """Meaningful, stemmed words of a text."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {_stem(w) for w in words if w not in STOPWORDS and len(w) > 2}


# ---------------------------------------------------------------- store ----

def _normalise(item: dict) -> dict | None:
    """Accept both the current schema and the original {memory, category} one."""
    text = str(item.get("memory", "")).strip()
    if not text:
        return None
    created = item.get("created_at") or _now()
    return {
        "id": item.get("id") or uuid.uuid4().hex[:8],
        "memory": text,
        "category": item.get("category") if item.get("category") in CATEGORIES else "preference",
        "created_at": created,
        "last_used_at": item.get("last_used_at"),
        "use_count": int(item.get("use_count", 0)),
    }


def load_memories() -> list[dict]:
    """Load all saved memories. A missing or unreadable file means no memories."""
    path = memory_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [m for m in (_normalise(item) for item in data if isinstance(item, dict)) if m]


def _write(memories: list[dict]) -> None:
    path = memory_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memories, indent=2), encoding="utf-8")


def get_memories() -> list[dict]:
    """Return all stored memories."""
    return load_memories()


def clear_memories() -> int:
    """Delete every stored memory. Returns how many were removed."""
    count = len(load_memories())
    _write([])
    return count


# ------------------------------------------------------------ similarity ----

def similarity(a: str, b: str) -> float:
    """Share of the shorter text's keywords that both texts have in common."""
    ka, kb = keywords(a), keywords(b)
    if not ka or not kb:
        return 0.0
    shared = ka & kb
    if len(shared) < min(MIN_SHARED, len(ka), len(kb)):
        return 0.0
    return len(shared) / min(len(ka), len(kb))


def save_memory(memory: str, category: str = "preference") -> dict:
    """Save a memory, consolidating it with similar memories of the same category.

    A preference and a skill are never merged, even if they share words. Of the
    merged memories, the most detailed wording is kept (the new one on a tie),
    with the earliest creation date and the total use count.
    Returns {"action": "added" | "consolidated", "merged": n, "memory": {...}}.
    """
    memories = load_memories()
    memory = memory.strip()
    if not memory:
        return {"action": "skipped", "merged": 0, "memory": None}

    new = _normalise({"memory": memory, "category": category})
    similar = [
        i
        for i, m in enumerate(memories)
        if m["category"] == new["category"] and similarity(memory, m["memory"]) >= MERGE_SIMILARITY
    ]

    if similar:
        merged = [memories[i] for i in similar]
        # Keep the most detailed wording so a vaguer restatement never erases detail.
        richest = max(merged, key=lambda m: len(keywords(m["memory"])))
        if len(keywords(richest["memory"])) > len(keywords(memory)):
            new["memory"] = richest["memory"]
        new["created_at"] = min(m["created_at"] for m in merged)
        new["use_count"] = sum(m["use_count"] for m in merged)
        used = [m["last_used_at"] for m in merged if m["last_used_at"]]
        new["last_used_at"] = max(used) if used else None
        first = similar[0]
        for i in reversed(similar):
            del memories[i]
        memories.insert(first, new)
        result = {"action": "consolidated", "merged": len(similar), "memory": new}
    else:
        memories.append(new)
        result = {"action": "added", "merged": 0, "memory": new}

    _write(memories)
    return result


def consolidate() -> int:
    """Merge similar memories already in the store. Returns how many were removed."""
    memories = load_memories()
    before = len(memories)
    _write([])
    for m in memories:
        save_memory(m["memory"], m["category"])
    # Restore usage metadata that a re-save would reset.
    after = load_memories()
    for m in after:
        sources = [
            old
            for old in memories
            if old["category"] == m["category"] and similarity(m["memory"], old["memory"]) >= MERGE_SIMILARITY
        ]
        if sources:
            m["created_at"] = min(s["created_at"] for s in sources)
            m["use_count"] = sum(s["use_count"] for s in sources)
            used = [s["last_used_at"] for s in sources if s["last_used_at"]]
            m["last_used_at"] = max(used) if used else None
    _write(after)
    return before - len(after)


# --------------------------------------------------------------- search ----

def search_memories(query: str, limit: int = 3) -> list[dict]:
    """Return up to `limit` memories relevant to the query, most relevant first.

    Relevance = share of the query's keywords that appear in the memory.
    Memories below MIN_RELEVANCE are left out, so unrelated tasks get nothing.
    """
    query_words = keywords(query)
    if not query_words:
        return []
    scored = []
    for m in load_memories():
        overlap = len(query_words & keywords(m["memory"]))
        score = overlap / len(query_words)
        if overlap and score >= MIN_RELEVANCE:
            scored.append((score, m))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [dict(m, relevance=round(score, 2)) for score, m in scored[:limit]]


def mark_used(memory_ids: list[str]) -> None:
    """Record that these memories were applied to a response."""
    if not memory_ids:
        return
    memories = load_memories()
    stamp = _now()
    for m in memories:
        if m["id"] in memory_ids:
            m["use_count"] += 1
            m["last_used_at"] = stamp
    _write(memories)
