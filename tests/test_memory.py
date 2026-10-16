"""Memory store: relevance search, consolidation, metadata. No LLM involved."""

import json

import memory_manager as mm

# The three near-duplicate memories the original demo had saved.
PARAPHRASES = [
    ("User prefers short, beginner-friendly technical explanations with a simple example.", "preference"),
    ("When explaining technical topics, use simple language and provide one practical example.", "instruction"),
    ("When giving technical explanations, keep them short, beginner-friendly, and include one simple real-world example.", "preference"),
]


def test_keywords_drop_filler_words_and_group_word_families():
    assert "a" not in mm.keywords("Write a short email to my team")
    assert mm.keywords("explain") == mm.keywords("explanations")
    assert mm.keywords("the and to of") == set()


def test_search_returns_only_relevant_memories(temp_memory):
    mm.save_memory("When explaining technical topics, give one practical example.", "skill")
    mm.save_memory("Summarize reports as bullet points.", "instruction")

    hits = mm.search_memories("Explain what a REST API is")
    assert [h["memory"] for h in hits] == ["When explaining technical topics, give one practical example."]
    assert mm.search_memories("Plan a birthday party") == []


def test_filler_words_no_longer_match_everything(temp_memory):
    # The original matched substrings like "a" and "to", so any task retrieved every memory.
    mm.save_memory("Summarize reports as bullet points.", "instruction")
    assert mm.search_memories("Write a note to my manager") == []


def test_search_is_ranked_and_limited(temp_memory):
    mm.save_memory("Explain database indexes with a diagram.", "skill")
    mm.save_memory("Explain things simply.", "preference")
    mm.save_memory("Explain database index trade-offs and costs.", "skill")
    mm.save_memory("Explain database queries step by step.", "skill")
    hits = mm.search_memories("Explain a database index", limit=2)
    assert len(hits) == 2
    assert hits[0]["relevance"] >= hits[1]["relevance"]


def test_paraphrased_duplicates_are_consolidated(temp_memory):
    for text, category in PARAPHRASES:
        mm.save_memory(text, category)
    memories = mm.load_memories()
    # The two preferences merge (keeping the most detailed wording); the instruction stays separate.
    assert [(m["category"], m["memory"]) for m in memories] == [
        ("preference", PARAPHRASES[2][0]),
        ("instruction", PARAPHRASES[1][0]),
    ]


def test_different_categories_are_never_merged(temp_memory):
    mm.save_memory("User prefers short, beginner-friendly explanations with one simple real-world example.", "preference")
    mm.save_memory("When explaining technical concepts, use a simple real-world analogy then a concrete example.", "skill")
    assert sorted(m["category"] for m in mm.load_memories()) == ["preference", "skill"]


def test_vaguer_restatement_does_not_erase_detail(temp_memory):
    detailed = "Keep technical explanations short, beginner-friendly, with one simple real-world example."
    mm.save_memory(detailed, "preference")
    mm.save_memory("Keep technical explanations short and simple.", "preference")
    [m] = mm.load_memories()
    assert m["memory"] == detailed


def test_unrelated_memories_are_not_merged(temp_memory):
    mm.save_memory("Summarize reports as bullet points.", "instruction")
    mm.save_memory("Explain technical topics with one practical example.", "skill")
    assert len(mm.load_memories()) == 2


def test_consolidate_cleans_an_existing_store(temp_memory):
    temp_memory.write_text(json.dumps([{"memory": t, "category": c} for t, c in PARAPHRASES]), encoding="utf-8")
    assert len(mm.load_memories()) == 3
    assert mm.consolidate() == 1
    assert len(mm.load_memories()) == 2


def test_legacy_entries_get_metadata(temp_memory):
    temp_memory.write_text(json.dumps([{"memory": "Use bullet points.", "category": "odd"}]), encoding="utf-8")
    [m] = mm.load_memories()
    assert m["id"] and m["created_at"]
    assert m["category"] == "preference"  # unknown categories fall back
    assert m["use_count"] == 0


def test_mark_used_tracks_usage(temp_memory):
    saved = mm.save_memory("Use bullet points for summaries.", "instruction")["memory"]
    mm.mark_used([saved["id"]])
    mm.mark_used([saved["id"]])
    [m] = mm.load_memories()
    assert m["use_count"] == 2 and m["last_used_at"]


def test_consolidation_keeps_usage_and_earliest_date(temp_memory):
    first = mm.save_memory(PARAPHRASES[0][0], "preference")["memory"]
    mm.mark_used([first["id"]])
    mm.save_memory(PARAPHRASES[2][0], "preference")
    [m] = mm.load_memories()
    assert m["memory"] == PARAPHRASES[2][0]
    assert m["use_count"] == 1
    assert m["created_at"] == first["created_at"]


def test_corrupt_file_means_no_memories(temp_memory):
    temp_memory.write_text("{not json", encoding="utf-8")
    assert mm.load_memories() == []


def test_clear_memories(temp_memory):
    mm.save_memory("Use bullet points.", "instruction")
    assert mm.clear_memories() == 1
    assert mm.load_memories() == []
