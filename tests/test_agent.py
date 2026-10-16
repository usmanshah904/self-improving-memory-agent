"""Agent loop with Claude replaced by canned replies (no CLI, no network)."""

import json

import agent
import memory_manager as mm

PREFERENCE = "When explaining technical topics, keep it short and beginner-friendly with one simple example."
FENCE = "`" * 3


def fake_claude(learning: str | None = None):
    prompts = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        if "learning component" in prompt:
            if learning is not None:
                return learning
            payload = json.dumps({"should_remember": True, "memory": PREFERENCE, "category": "preference"})
            return f"{FENCE}json\n{payload}\n{FENCE}"
        return "An API is how programs talk to each other. Example: a weather app asks a server for today's forecast."

    ask.prompts = prompts
    return ask


def test_parse_learning_handles_code_fences_and_extra_text():
    payload = json.dumps({"should_remember": True, "memory": "Use bullet points.", "category": "instruction"})
    for reply in (payload, f"{FENCE}json\n{payload}\n{FENCE}", f"Here you go:\n{payload}\nHope that helps!"):
        assert agent.parse_learning(reply) == {"memory": "Use bullet points.", "category": "instruction"}


def test_parse_learning_rejects_nothing_to_learn_and_bad_json():
    assert agent.parse_learning('{"should_remember": false, "memory": "", "category": ""}') is None
    assert agent.parse_learning("no json here") is None
    assert agent.parse_learning("{broken") is None
    odd = agent.parse_learning('{"should_remember": true, "memory": "x y z", "category": "mood"}')
    assert odd["category"] == "preference"


def test_run_one_learns_and_run_two_applies_it(monkeypatch):
    ask = fake_claude()
    monkeypatch.setattr(agent, "ask_claude", ask)

    # Run 1: nothing known yet; the preference is learned and saved.
    assert agent.run_agent("Explain what an API is. I prefer short, beginner-friendly answers.") == 0
    assert "No relevant memories found." in ask.prompts[0]
    [saved] = mm.load_memories()
    assert saved["memory"] == PREFERENCE

    # Run 2: a related task retrieves the preference and passes it to Claude.
    assert agent.run_agent("Explain what a database index is") == 0
    assert PREFERENCE in ask.prompts[2]
    [after] = mm.load_memories()
    assert after["use_count"] == 1  # applied once


def test_unrelated_task_gets_no_memories(monkeypatch):
    mm.save_memory(PREFERENCE, "preference")
    ask = fake_claude(learning='{"should_remember": false, "memory": "", "category": ""}')
    monkeypatch.setattr(agent, "ask_claude", ask)
    agent.run_agent("Plan a birthday party")
    assert "No relevant memories found." in ask.prompts[0]


def test_claude_error_stops_the_run_without_saving(monkeypatch):
    monkeypatch.setattr(agent, "ask_claude", lambda prompt: "ERROR: Claude timed out.")
    assert agent.run_agent("Explain what an API is") == 1
    assert mm.load_memories() == []


def test_missing_cli_is_reported(monkeypatch):
    monkeypatch.setattr(agent.shutil, "which", lambda _: None)
    assert agent.ask_claude("hi").startswith("ERROR: Claude Code CLI was not found")


def test_cli_show_and_reset(capsys, tmp_path):
    store = tmp_path / "demo.json"
    assert agent.main(["--memory-file", str(store), "--show-memories"]) == 0
    assert "No memories saved yet." in capsys.readouterr().out
    mm.save_memory("Use bullet points for summaries.", "instruction")  # same store via env
    assert agent.main(["--memory-file", str(store), "--show-memories"]) == 0
    assert "Use bullet points" in capsys.readouterr().out
    assert agent.main(["--memory-file", str(store), "--reset"]) == 0
    assert mm.load_memories() == []
