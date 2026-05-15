"""Desktop operation planning for visual local control."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DesktopStep:
    action: str
    target: str = ""
    narration: str = ""
    requires_approval: bool = False


@dataclass(frozen=True)
class DesktopJob:
    mode: str
    steps: tuple[DesktopStep, ...]
    visual: bool = True
    approval_required: bool = False
    reason: str = ""


SENSITIVE_ACTION_RE = re.compile(r"\b(login|password|pay|purchase|post|send|delete|format|install|uninstall)\b", re.I)


def plan(text: str) -> DesktopJob:
    lower = " ".join(str(text or "").lower().split())
    steps: list[DesktopStep] = [
        DesktopStep("inspect-screen", narration="Inspect the current visible desktop state."),
    ]
    if any(term in lower for term in ("move", "mouse", "cursor")):
        steps.append(DesktopStep("move-pointer", narration="Move the pointer to the requested target."))
    if any(term in lower for term in ("click", "press", "button")):
        steps.append(DesktopStep("click", narration="Click only after the target is visually confirmed."))
    if any(term in lower for term in ("type", "write", "enter")):
        steps.append(DesktopStep("type", narration="Type the requested text into the confirmed active field."))
    if any(term in lower for term in ("screenshot", "screen", "visible", "visual")):
        steps.append(DesktopStep("capture-screen", narration="Capture evidence of the visible state."))

    approval_required = bool(SENSITIVE_ACTION_RE.search(lower))
    if approval_required:
        steps = [
            step if step.action in {"inspect-screen", "capture-screen"} else DesktopStep(
                step.action,
                target=step.target,
                narration=step.narration,
                requires_approval=True,
            )
            for step in steps
        ]
    return DesktopJob(
        mode="approval-gated-desktop" if approval_required else "visual-desktop",
        steps=tuple(steps),
        approval_required=approval_required,
        reason="desktop lane selected from prompt terms",
    )


def narration(job: DesktopJob) -> str:
    return "\n".join(f"- {step.action}: {step.narration}" for step in job.steps)
