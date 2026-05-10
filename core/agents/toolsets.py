from __future__ import annotations


READ_ONLY_TOOLS = frozenset({
    "read_file",
    "read_media",
    "list_files",
    "glob",
    "grep",
    "git",
    "web_fetch",
    "web_search",
    "bash",
})

WORKER_TOOLS = READ_ONLY_TOOLS | frozenset({"write_file", "edit_file", "multi_edit"})
