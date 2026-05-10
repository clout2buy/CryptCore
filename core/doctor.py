"""Local harness self-checks for Crypt."""
from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from tools import REGISTRY

from . import background, evidence, file_state, final_claims, prompt, redact, session, tool_policy, verifiers
from .agents import registry as agent_registry


FORBIDDEN_IDENTITY = ("Claude " + "Code", "Claude " + "OAuth", "claude" + "-cli")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def run_doctor(cwd: str | Path) -> str:
    cwd = Path(cwd).resolve()
    checks = [
        _check_prompt(cwd),
        _check_registry(),
        _check_tool_load_failures(),
        _check_session(),
        _check_file_state(),
        _check_background(),
        _check_redaction(),
        _check_identity_strings(cwd),
        _check_ripgrep(),
        _check_app_dir_writable(),
        _check_provider_auth(),
        _check_known_model(),
        _check_agent_registry(),
        _check_evidence_ledger(),
        _check_verifier_contract(),
        _check_final_claim_guard(),
        _check_tool_policy(),
    ]
    passed = sum(1 for c in checks if c.ok)
    lines = [f"Crypt doctor: {passed}/{len(checks)} checks passed"]
    for check in checks:
        mark = "OK" if check.ok else "FAIL"
        suffix = f" - {check.detail}" if check.detail else ""
        lines.append(f"[{mark}] {check.name}{suffix}")
    return "\n".join(lines)


def _check_prompt(cwd: Path) -> Check:
    try:
        text = prompt.build_system_prompt(
            provider_name="doctor",
            model="doctor",
            cwd=str(cwd),
            tool_guidance="",
        )
        if "You are Crypt" not in text:
            return Check("prompt identity", False, "missing Crypt identity")
        bad = [s for s in FORBIDDEN_IDENTITY if s.lower() in text.lower()]
        if bad:
            return Check("prompt identity", False, f"forbidden string: {bad[0]}")
        return Check("prompt identity", True)
    except Exception as e:
        return Check("prompt identity", False, f"{type(e).__name__}: {e}")


def _check_registry() -> Check:
    try:
        names = [item["name"] for item in REGISTRY.schemas()]
        sub = [item["name"] for item in REGISTRY.schemas(for_subagent=True)]
        required = {
            "read_file",
            "edit_file",
            "bash_start",
            "web_fetch",
            "spawn_agent",
            "list_agents",
            "agent_output",
            "send_agent_message",
            "stop_agent",
        }
        missing = sorted(required - set(names))
        if missing:
            return Check("tool registry", False, "missing " + ", ".join(missing))
        disallowed = {"edit_file", "write_file", "bash", "ask_user", "present_plan"} & set(sub)
        if disallowed:
            return Check("subagent tool boundary", False, "leaks " + ", ".join(sorted(disallowed)))
        return Check("tool registry", True, f"{len(names)} tools, {len(sub)} subagent tools")
    except Exception as e:
        return Check("tool registry", False, f"{type(e).__name__}: {e}")


def _check_agent_registry() -> Check:
    try:
        names = set(agent_registry.agent_names())
        required = {"explorer", "planner", "worker", "verifier", "ui_reviewer", "release_reviewer"}
        missing = sorted(required - names)
        if missing:
            return Check("agent registry", False, "missing " + ", ".join(missing))
        worker = agent_registry.get_agent("worker")
        if worker.read_only or not worker.requires_write_paths:
            return Check("agent registry", False, "worker contract is not scoped-write")
        return Check("agent registry", True, f"{len(names)} agent types")
    except Exception as e:
        return Check("agent registry", False, f"{type(e).__name__}: {e}")


def _check_evidence_ledger() -> Check:
    try:
        evidence.clear()
        evidence.record_tool_result("bash", {"command": "python -m pytest -q tests/test_example.py"}, ok=True, output="1 passed")
        ok = evidence.has_passing_verification()
        return Check("evidence ledger", ok, evidence.evidence_summary(2))
    except Exception as e:
        return Check("evidence ledger", False, f"{type(e).__name__}: {e}")
    finally:
        evidence.clear()


def _check_verifier_contract() -> Check:
    try:
        result = verifiers.parse_verifier_output("Command: python -m pytest -q\nVERDICT: PASS")
        return Check("verifier contract", result.status == "PASS" and result.commands, result.status)
    except Exception as e:
        return Check("verifier contract", False, f"{type(e).__name__}: {e}")


def _check_final_claim_guard() -> Check:
    try:
        evidence.clear()
        guarded, note = final_claims.guard_text("Done, implemented.")
        ok = bool(note and "unverified" in guarded)
        return Check("final claim guard", ok)
    except Exception as e:
        return Check("final claim guard", False, f"{type(e).__name__}: {e}")
    finally:
        evidence.clear()


def _check_tool_policy() -> Check:
    try:
        tool_policy.clear()
        args = {"path": "doctor-artifact.html", "content": "<html></html>"}
        first = tool_policy.preflight("write_file", args)
        tool_policy.after_tool("write_file", args, ok=True)
        second = tool_policy.preflight("write_file", args)
        ok = first.action == tool_policy.ALLOW and second.action == tool_policy.WARN
        return Check("tool policy", ok, second.reason if second.reason else "")
    except Exception as e:
        return Check("tool policy", False, f"{type(e).__name__}: {e}")
    finally:
        tool_policy.clear()


def _check_session() -> Check:
    try:
        with tempfile.TemporaryDirectory(prefix="crypt-doctor-session-") as td:
            s = session.Session(td, provider="doctor", model="doctor")
            s.record_message({"role": "user", "content": "doctor user"})
            s.record_message({"role": "assistant", "content": [{"type": "text", "text": "doctor assistant"}]})
            loaded = s.load_messages()
            ok = len(loaded) == 2 and loaded[0]["content"] == "doctor user"
            path = s.path
            try:
                path.unlink(missing_ok=True)
                path.parent.rmdir()
            except OSError:
                pass
            return Check("session persistence", ok, str(path) if ok else "replay mismatch")
    except Exception as e:
        return Check("session persistence", False, f"{type(e).__name__}: {e}")


def _check_file_state() -> Check:
    try:
        with tempfile.TemporaryDirectory(prefix="crypt-doctor-file-") as td:
            path = Path(td) / "sample.txt"
            path.write_text("alpha\n", encoding="utf-8")
            file_state.clear()
            try:
                file_state.assert_fresh_for_edit(path)
                return Check("read-before-edit", False, "unread file was accepted")
            except PermissionError:
                pass
            data = path.read_bytes()
            file_state.record_read(path, data)
            file_state.assert_fresh_for_edit(path)
            path.write_text("beta gamma\n", encoding="utf-8")
            try:
                file_state.assert_fresh_for_edit(path)
                return Check("stale-file protection", False, "changed file was accepted")
            except RuntimeError:
                pass
            return Check("read-before-edit", True)
    except Exception as e:
        return Check("read-before-edit", False, f"{type(e).__name__}: {e}")
    finally:
        file_state.clear()


def _check_background() -> Check:
    try:
        with tempfile.TemporaryDirectory(prefix="crypt-doctor-bg-") as td:
            job = background.start('python -c "print(12345)"', cwd=td, description="doctor")
            deadline = time.time() + 5
            while time.time() < deadline and job.process.poll() is None:
                time.sleep(0.05)
            if job.process.poll() is None:
                background.kill(job.id)
                try:
                    job.output_path.unlink(missing_ok=True)
                    job.output_path.parent.rmdir()
                except OSError:
                    pass
                background.forget(job.id)
                return Check("background jobs", False, "job did not exit")
            out = background.poll(job.id, tail_lines=20)
            try:
                job.output_path.unlink(missing_ok=True)
                job.output_path.parent.rmdir()
            except OSError:
                pass
            background.forget(job.id)
            return Check("background jobs", "12345" in out, f"job {job.id}")
    except Exception as e:
        return Check("background jobs", False, f"{type(e).__name__}: {e}")


def _check_redaction() -> Check:
    name = "CRYPT_DOCTOR_TOKEN"
    value = "doctor-secret-value-12345"
    old = os.environ.get(name)
    os.environ[name] = value
    try:
        cleaned = redact.text(f"token={value}")
        return Check("secret redaction", value not in cleaned)
    except Exception as e:
        return Check("secret redaction", False, f"{type(e).__name__}: {e}")
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


def _check_identity_strings(cwd: Path) -> Check:
    """Scan only user-facing files (README + main.py) for forbidden identity
    strings. The system prompt is checked separately by _check_prompt. Code
    comments that cite reference implementations as a design source are fine
    — that's attribution, not impersonation."""
    try:
        targets = [cwd / "README.md", cwd / "main.py"]
        hits: list[str] = []
        for target in targets:
            if target.is_file():
                _scan_file(target, hits)
            if hits:
                break
        if hits:
            return Check("Crypt-facing identity strings", False, hits[0])
        return Check("Crypt-facing identity strings", True)
    except Exception as e:
        return Check("Crypt-facing identity strings", False, f"{type(e).__name__}: {e}")


def _check_tool_load_failures() -> Check:
    failures = REGISTRY.load_failures()
    if not failures:
        return Check("tool load", True, "all tool modules imported")
    detail = "; ".join(f"{name}: {err}" for name, err in failures[:3])
    if len(failures) > 3:
        detail += f"; (+{len(failures) - 3} more)"
    return Check("tool load", False, detail)


def _check_ripgrep() -> Check:
    import shutil
    import subprocess

    rg = shutil.which("rg")
    if rg:
        try:
            r = subprocess.run([rg, "--version"], capture_output=True, text=True, timeout=5)
        except Exception as e:
            return Check(
                "ripgrep (rg)",
                True,
                f"{rg} found but not executable ({type(e).__name__}); grep falls back to Python",
            )
        if r.returncode == 0:
            version = (r.stdout or "").splitlines()[0] if r.stdout else rg
            return Check("ripgrep (rg)", True, version)
        detail = (r.stderr or r.stdout or "").strip()[:160] or f"exit {r.returncode}"
        return Check("ripgrep (rg)", True, f"{rg} failed ({detail}); grep falls back to Python")
    # Soft warning — Python fallback exists. Surface as a non-blocking note.
    return Check(
        "ripgrep (rg)",
        True,
        "not found; grep falls back to Python (slower on large repos)",
    )


def _check_app_dir_writable() -> Check:
    from .settings import APP_DIR

    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        probe = APP_DIR / ".doctor-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return Check("app dir writable", True, str(APP_DIR))
    except OSError as e:
        return Check("app dir writable", False, f"{APP_DIR}: {e}")


def _check_provider_auth() -> Check:
    from . import auth
    from .settings import (
        PROVIDER_ANTHROPIC,
        PROVIDER_OLLAMA,
        PROVIDER_OPENAI,
        PROVIDER_OPENAI_CODEX,
        PROVIDER_GEMINI,
        is_local_host,
        is_ollama_cloud_host,
        load_config,
        ollama_host,
        provider_default,
    )

    try:
        saved = load_config()
        provider = provider_default(saved)
        if provider == PROVIDER_ANTHROPIC:
            stored = auth.load_provider("anthropic") or {}
            if os.getenv("ANTHROPIC_API_KEY") or stored.get("access"):
                return Check("provider auth", True, "Anthropic credentials available")
            return Check("provider auth", False, "Anthropic selected; run login or set ANTHROPIC_API_KEY")

        if provider == PROVIDER_OPENAI:
            if os.getenv("OPENAI_API_KEY"):
                return Check("provider auth", True, "OPENAI_API_KEY is set")
            return Check("provider auth", False, "OpenAI selected; set OPENAI_API_KEY")

        if provider == PROVIDER_OPENAI_CODEX:
            stored = auth.load_provider("openai-codex") or {}
            if stored.get("access") and stored.get("account_id"):
                return Check("provider auth", True, "ChatGPT OAuth credentials available")
            return Check("provider auth", False, "OpenAI Codex selected; run login --provider openai-codex")

        if provider == PROVIDER_GEMINI:
            if os.getenv("GEMINI_API_KEY"):
                return Check("provider auth", True, "GEMINI_API_KEY is set")
            stored_cred = auth.resolve_gemini()
            if stored_cred and stored_cred.project_id:
                return Check("provider auth", True, "Gemini Google OAuth credentials available")
            if stored_cred:
                return Check("provider auth", True, "Gemini Google OAuth credentials available without Vertex project")
            if auth.resolve_gemini(include_adc=True):
                return Check("provider auth", True, "Gemini Application Default Credentials available")
            return Check("provider auth", False, "Gemini selected; set GEMINI_API_KEY or run login --provider gemini")

        if provider == PROVIDER_OLLAMA:
            host = ollama_host(saved=saved)
            if is_ollama_cloud_host(host):
                if os.getenv("OLLAMA_API_KEY"):
                    return Check("provider auth", True, f"Ollama Cloud key available for {host}")
                return Check(
                    "provider auth",
                    False,
                    "Ollama Cloud selected; set OLLAMA_API_KEY. Anthropic login is not used for Ollama.",
                )
            if is_local_host(host):
                return Check("provider auth", True, f"local Ollama host {host}; no key required by Crypt")
            detail = f"custom Ollama host {host}; using OLLAMA_API_KEY if set, otherwise default bearer token"
            return Check("provider auth", True, detail)

        return Check("provider auth", False, f"unknown provider {provider!r}")
    except Exception as e:
        return Check("provider auth", False, f"{type(e).__name__}: {e}")


def _check_known_model() -> Check:
    """Best-effort: warn if the configured Anthropic model isn't in the
    known list. Avoids the 'I configured an old model and got a 404 in
    week 3' failure mode."""
    from .settings import (
        ANTHROPIC_MODELS,
        OLLAMA_MODELS,
        OPENAI_MODELS,
        OPENAI_CODEX_MODELS,
        GEMINI_MODELS,
        load_config,
        provider_default,
        model_default,
    )

    saved = load_config()
    provider = provider_default(saved)
    model = model_default(provider, saved)
    if provider == "anthropic":
        known = ANTHROPIC_MODELS
    elif provider == "openai":
        known = OPENAI_MODELS
    elif provider == "openai-codex":
        known = OPENAI_CODEX_MODELS
    elif provider == "gemini":
        known = GEMINI_MODELS
    else:
        known = OLLAMA_MODELS
    if model in known:
        return Check("model is known", True, f"{provider}:{model}")
    return Check(
        "model is known",
        True,
        f"{provider}:{model} not in known list (may still work; update settings.py if it does)",
    )


def _scan_file(path: Path, hits: list[str]) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    low = text.lower()
    for needle in FORBIDDEN_IDENTITY:
        if needle.lower() in low:
            hits.append(f"{path}:{needle}")
            return
