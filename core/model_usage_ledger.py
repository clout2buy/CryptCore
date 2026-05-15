"""Provider/model usage, latency, success, and rough cost ledger."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import session, settings


SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ModelRun:
    run_id: str
    cwd: str
    provider: str
    model: str
    task_id: str = ""
    task_type: str = ""
    ok: bool = True
    latency_ms: int = 0
    input_tokens_est: int = 0
    output_tokens_est: int = 0
    total_tokens_est: int = 0
    cost_usd_est: float = 0.0
    error: str = ""
    created_at: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def ledger_path(cwd: str | Path) -> Path:
    return session.project_dir(cwd) / "model_usage" / "runs.json"


def record_run(
    cwd: str | Path,
    *,
    provider: str,
    model: str,
    task_id: str = "",
    task_type: str = "",
    ok: bool = True,
    latency_ms: int = 0,
    total_tokens: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error: str = "",
) -> ModelRun:
    root = Path(cwd).expanduser().resolve()
    total = max(0, int(total_tokens or input_tokens + output_tokens))
    if total and not input_tokens and not output_tokens:
        input_tokens = int(total * 0.8)
        output_tokens = total - input_tokens
    run = ModelRun(
        run_id="run_" + uuid.uuid4().hex[:10],
        cwd=str(root),
        provider=settings.normalize_provider(provider),
        model=str(model or ""),
        task_id=str(task_id or ""),
        task_type=str(task_type or ""),
        ok=bool(ok),
        latency_ms=max(0, int(latency_ms or 0)),
        input_tokens_est=max(0, int(input_tokens or 0)),
        output_tokens_est=max(0, int(output_tokens or 0)),
        total_tokens_est=total,
        cost_usd_est=_estimate_cost(provider, model, input_tokens, output_tokens),
        error=_clean(error, 500),
        created_at=_now(),
    )
    rows = list_runs(root, limit=1_000)
    rows.insert(0, run)
    _write(root, rows[:500])
    return run


def list_runs(cwd: str | Path, *, limit: int = 100) -> list[ModelRun]:
    rows = _read(cwd)
    rows.sort(key=lambda row: row.created_at, reverse=True)
    return rows[: max(1, limit)]


def snapshot(cwd: str | Path) -> dict[str, Any]:
    rows = list_runs(cwd, limit=200)
    return {
        "total": len(rows),
        "success": sum(1 for row in rows if row.ok),
        "failed": sum(1 for row in rows if not row.ok),
        "tokensEstimated": sum(row.total_tokens_est for row in rows),
        "costEstimatedUsd": round(sum(row.cost_usd_est for row in rows), 6),
        "avgLatencyMs": int(sum(row.latency_ms for row in rows) / len(rows)) if rows else 0,
        "byModel": _by_model(rows),
        "runs": [row.to_dict() for row in rows[:12]],
    }


def prompt_section(cwd: str | Path, *, limit: int = 5) -> str:
    rows = list_runs(cwd, limit=limit)
    if not rows:
        return ""
    snap = snapshot(cwd)
    lines = [
        "# Model Usage Ledger",
        f"- runs={snap['total']}; success={snap['success']}; failed={snap['failed']}; estimated_cost=${snap['costEstimatedUsd']:.6f}; avg_latency={snap['avgLatencyMs']}ms",
    ]
    for row in rows[:limit]:
        lines.append(f"- {row.provider}/{row.model}: ok={row.ok}; tokens~{row.total_tokens_est}; latency={row.latency_ms}ms")
    return "\n".join(lines)


def _by_model(rows: list[ModelRun]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[ModelRun]] = {}
    for row in rows:
        grouped.setdefault((row.provider, row.model), []).append(row)
    out = []
    for (provider, model), items in grouped.items():
        out.append(
            {
                "provider": provider,
                "model": model,
                "runs": len(items),
                "success": sum(1 for item in items if item.ok),
                "failed": sum(1 for item in items if not item.ok),
                "tokensEstimated": sum(item.total_tokens_est for item in items),
                "costEstimatedUsd": round(sum(item.cost_usd_est for item in items), 6),
                "avgLatencyMs": int(sum(item.latency_ms for item in items) / len(items)) if items else 0,
            }
        )
    out.sort(key=lambda item: (item["runs"], item["tokensEstimated"]), reverse=True)
    return out


def _estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    price = _price_per_million(provider, model)
    return round((max(0, input_tokens) * price["input"] + max(0, output_tokens) * price["output"]) / 1_000_000, 6)


def _price_per_million(provider: str, model: str) -> dict[str, float]:
    provider = settings.normalize_provider(provider)
    model_l = str(model or "").lower()
    if provider in {settings.PROVIDER_OLLAMA}:
        return {"input": 0.0, "output": 0.0}
    if "spark" in model_l or "mini" in model_l:
        return {"input": 0.15, "output": 0.60}
    if "5.5" in model_l or "opus" in model_l or "max" in model_l:
        return {"input": 3.0, "output": 12.0}
    if "gemini" in model_l:
        return {"input": 0.35, "output": 1.05}
    return {"input": 1.0, "output": 4.0}


def _read(cwd: str | Path) -> list[ModelRun]:
    path = ledger_path(cwd)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict) or int(data.get("schema") or 0) != SCHEMA_VERSION:
        return []
    rows = []
    for item in data.get("runs", []):
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                ModelRun(
                    run_id=str(item.get("run_id") or ""),
                    cwd=str(item.get("cwd") or ""),
                    provider=settings.normalize_provider(str(item.get("provider") or "")),
                    model=str(item.get("model") or ""),
                    task_id=str(item.get("task_id") or ""),
                    task_type=str(item.get("task_type") or ""),
                    ok=bool(item.get("ok", True)),
                    latency_ms=int(item.get("latency_ms") or 0),
                    input_tokens_est=int(item.get("input_tokens_est") or 0),
                    output_tokens_est=int(item.get("output_tokens_est") or 0),
                    total_tokens_est=int(item.get("total_tokens_est") or 0),
                    cost_usd_est=float(item.get("cost_usd_est") or 0.0),
                    error=str(item.get("error") or ""),
                    created_at=int(item.get("created_at") or 0),
                )
            )
        except Exception:
            continue
    return [row for row in rows if row.run_id and row.cwd]


def _write(cwd: str | Path, rows: list[ModelRun]) -> None:
    path = ledger_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema": SCHEMA_VERSION, "runs": [row.to_dict() for row in rows]}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    settings.restrict_file_permissions(path)


def _clean(value: str, limit: int) -> str:
    clean = " ".join(str(value or "").split())
    return clean if len(clean) <= limit else clean[: limit - 3].rstrip() + "..."


def _now() -> int:
    return int(time.time())
