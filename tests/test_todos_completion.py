from __future__ import annotations

from core import loop
from tools import todos


def test_artifact_final_auto_completes_stale_todos(workspace):
    todos.run({
        "todos": [
            {"text": "Create HTML structure", "status": "doing"},
            {"text": "Add animation", "status": "pending"},
        ]
    })
    messages = [
        {"role": "user", "content": "make me an animated html and open it"},
        {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "write_1",
                "name": "write_file",
                "input": {"path": "demo.html", "content": "<!doctype html>"},
            }],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "write_1",
                "content": "created demo.html",
                "is_error": False,
            }],
        },
        {
            "role": "assistant",
            "content": [{"type": "text", "text": "Created and opened it."}],
        },
    ]

    loop._maybe_complete_todos_after_final(messages)

    assert todos.get_todos()
    assert all(item["status"] == "done" for item in todos.get_todos())


def test_non_artifact_final_leaves_open_todos_alone(workspace):
    todos.run({
        "todos": [
            {"text": "Investigate issue", "status": "doing"},
            {"text": "Patch issue", "status": "pending"},
        ]
    })
    messages = [
        {"role": "user", "content": "look into this bug"},
        {
            "role": "assistant",
            "content": [{
                "type": "tool_use",
                "id": "read_1",
                "name": "read_file",
                "input": {"path": "README.md"},
            }],
        },
        {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "read_1",
                "content": "contents",
                "is_error": False,
            }],
        },
    ]

    loop._maybe_complete_todos_after_final(messages)

    statuses = [item["status"] for item in todos.get_todos()]
    assert statuses == ["doing", "pending"]
