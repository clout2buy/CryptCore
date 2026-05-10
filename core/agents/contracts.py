from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class AgentTaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    system_prompt: str
    allowed_tools: frozenset[str]
    output_contract: str
    read_only: bool = True
    requires_write_paths: bool = False
    ui_label: str = "agent"
    default_mode: str = "sync"

    @property
    def can_write(self) -> bool:
        return not self.read_only


@dataclass(frozen=True)
class AgentRequest:
    description: str
    prompt: str
    agent_type: str = "explorer"
    name: str = ""
    mode: str = "sync"
    scope: str = ""
    write_paths: tuple[str, ...] = field(default_factory=tuple)
    isolation: str = "shared"
    context: str | None = None
