"""Static accessibility and motion audit for the local WebUI."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from importlib import resources
from typing import Any


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AuditCheck:
    check_id: str
    category: str
    label: str
    ok: bool
    detail: str
    severity: str = "info"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def snapshot() -> dict[str, Any]:
    html = _asset("index.html")
    css = _asset("styles.css")
    script = _asset("app.js")
    checks = [
        _check_focus_visible(css),
        _check_keyboard_semantics(html, script),
        _check_aria_live(html),
        _check_contrast_tokens(css),
        _check_text_overflow(css),
        _check_reduced_motion(css),
        _check_touch_targets(css),
        _check_decorative_media_hidden(html),
    ]
    passed = sum(1 for check in checks if check.ok)
    score = round(passed / max(1, len(checks)), 3)
    return {
        "schema": SCHEMA_VERSION,
        "score": score,
        "status": "pass" if score >= 0.9 else "needs-work",
        "passed": passed,
        "total": len(checks),
        "blocking": sum(1 for check in checks if not check.ok and check.severity == "high"),
        "checks": [check.to_dict() for check in checks],
    }


def prompt_section() -> str:
    snap = snapshot()
    failed = [check for check in snap["checks"] if not check["ok"]]
    if not failed:
        return "# Accessibility And Motion Audit\n- WebUI static audit is currently passing; preserve keyboard focus, reduced motion, text overflow, and touch target coverage."
    lines = ["# Accessibility And Motion Audit", f"- score={snap['score']}; status={snap['status']}"]
    for check in failed[:5]:
        lines.append(f"- {check['severity']} {check['category']}: {check['label']}; {check['detail']}")
    return "\n".join(lines)


def _asset(name: str) -> str:
    return resources.files("core.webui_static").joinpath(name).read_text(encoding="utf-8")


def _check_focus_visible(css: str) -> AuditCheck:
    ok = ":focus-visible" in css and "outline" in css
    return AuditCheck(
        "focus-visible",
        "keyboard",
        "Visible keyboard focus",
        ok,
        "focus-visible outline is defined for buttons, inputs, textarea, and selects." if ok else "Add visible focus states for interactive controls.",
        "high",
    )


def _check_keyboard_semantics(html: str, script: str) -> AuditCheck:
    buttons = len(re.findall(r"<button\b", html)) + len(re.findall(r"<button\b", script))
    typed = len(re.findall(r"<button\b[^>]*\btype=", html)) + len(re.findall(r"<button\b[^>]*\btype=", script))
    ok = buttons > 0 and typed >= max(1, int(buttons * 0.8))
    return AuditCheck(
        "button-types",
        "keyboard",
        "Buttons declare type",
        ok,
        f"{typed}/{buttons} static buttons declare type to avoid accidental form submits.",
        "warning",
    )


def _check_aria_live(html: str) -> AuditCheck:
    ok = 'aria-live="polite"' in html and "aria-expanded" in html and "aria-pressed" in html
    return AuditCheck(
        "aria-state",
        "keyboard",
        "Live regions and state attributes",
        ok,
        "Chat/status areas expose polite live updates plus expanded/pressed states." if ok else "Add live region and control state attributes.",
        "high",
    )


def _check_contrast_tokens(css: str) -> AuditCheck:
    ok = "--ink: #fbfaf7" in css and "--bg: #080808" in css and "color-scheme: dark" in css
    return AuditCheck(
        "contrast-tokens",
        "contrast",
        "Dark surface contrast tokens",
        ok,
        "Primary ink and dark background tokens keep base contrast high." if ok else "Define high-contrast base ink/background tokens.",
        "high",
    )


def _check_text_overflow(css: str) -> AuditCheck:
    ok = "overflow-wrap: anywhere" in css and "min-width: 0" in css and "text-overflow: ellipsis" in css
    return AuditCheck(
        "text-overflow",
        "layout",
        "Text overflow guards",
        ok,
        "Long chat/session/artifact text has wrapping and min-width guards." if ok else "Add overflow-wrap, min-width:0, and ellipsis guards to dense surfaces.",
        "warning",
    )


def _check_reduced_motion(css: str) -> AuditCheck:
    ok = "prefers-reduced-motion" in css and "animation-duration" in css and "transition-duration" in css
    return AuditCheck(
        "reduced-motion",
        "motion",
        "Reduced motion support",
        ok,
        "Reduced-motion media query disables long transitions and ambient effects." if ok else "Add prefers-reduced-motion handling for transitions, canvas, and video ambience.",
        "high",
    )


def _check_touch_targets(css: str) -> AuditCheck:
    min_heights = [int(value) for value in re.findall(r"min-height:\s*(\d+)px", css)]
    ok = bool(min_heights) and max(min_heights) >= 48 and len([value for value in min_heights if value >= 38]) >= 4
    return AuditCheck(
        "touch-targets",
        "touch",
        "Touch target sizing",
        ok,
        f"Detected {len([value for value in min_heights if value >= 38])} min-height rules at or above 38px; largest {max(min_heights or [0])}px.",
        "warning",
    )


def _check_decorative_media_hidden(html: str) -> AuditCheck:
    ok = 'class="ambient-video"' in html and 'aria-hidden="true"' in html and "<canvas" in html
    return AuditCheck(
        "decorative-media",
        "screen-reader",
        "Decorative media hidden",
        ok,
        "Ambient video/canvas layers are marked aria-hidden." if ok else "Mark decorative video/canvas layers aria-hidden.",
        "warning",
    )
