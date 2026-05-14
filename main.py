"""crypt - local-first coding harness.

Examples:
    python main.py
    python main.py setup
    python main.py login
    python main.py --provider ollama --model gpt-oss:120b-cloud
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from core import auth, runtime, session as sessions, settings, ui
from core.api import AnthropicProvider, CryptProvider, GeminiProvider, OllamaProvider, OpenAIProvider
from core.loop import run


def main() -> int:
    load_dotenv(Path(__file__).with_name(".env"))
    load_dotenv()
    saved = settings.load_config()

    p = argparse.ArgumentParser(prog="crypt", description="local-first coding harness")
    p.add_argument(
        "--provider",
        choices=settings.PROVIDER_CHOICES,
        help="anthropic oauth, openai-compatible, crypt oauth, gemini, or ollama",
    )
    p.add_argument("--model", help="model id; overrides saved/default model")
    p.add_argument("--cwd", help="workspace root for tools")
    p.add_argument("--max-tokens", type=int, help="Anthropic response token cap")
    p.add_argument("--thinking-budget", type=int, help="Anthropic thinking token budget")
    p.add_argument("--ollama-host", help="Ollama host, usually http://localhost:11434")
    p.add_argument(
        "--show-thinking",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="display the model's raw thinking stream (default: off; pass --show-thinking to show)",
    )
    p.add_argument("--no-thinking", action="store_true", help="disable extended thinking")
    p.add_argument("--no-picker", action="store_true", help="skip startup provider/model picker")
    p.add_argument("--resume", action="store_true", help="resume the latest Crypt session for this workspace")
    p.add_argument("--session", help="resume a specific Crypt session id or title prefix")
    p.add_argument("--bench-suite", default=None, help="benchmark suite JSON path")
    p.add_argument("--bench-task", action="append", help="benchmark task id to run; repeatable")
    p.add_argument("--bench-max-tasks", type=int, help="maximum benchmark tasks to run")
    p.add_argument("--bench-output", help="directory for benchmark run artifacts")
    p.add_argument("--bench-list", action="store_true", help="list benchmark tasks without running a provider")
    p.add_argument("--eval-prompt", help="prompt for eval-target; defaults to production upgrade prompt")
    p.add_argument("--eval-check", action="append", help="verification command for eval-target; repeatable")
    p.add_argument("--eval-output", help="directory for eval-target artifacts")
    p.add_argument("--eval-max-turns", type=int, default=60, help="max model turns for eval-target")
    p.add_argument(
        "--eval-forbid-access",
        action="append",
        help="forbidden path glob for eval-target trace review; repeatable",
    )
    p.add_argument("--eval-no-clean", action="store_true", help="do not remove new generated cache artifacts")
    p.add_argument("--eval-json", action="store_true", help="print eval-target JSON report")
    p.add_argument(
        "command",
        nargs="?",
        choices=[
            "login",
            "logout",
            "setup",
            "doctor",
            "bench",
            "eval-target",
            "app-daemon",
            "skills",
            "tasks",
            "project",
            "learn",
            "reflect",
            "goals",
            "forge",
            "autonomy",
            "webui",
        ],
        help=(
            "login | logout | setup | doctor | bench | eval-target | app-daemon | "
            "skills | tasks | project | learn | reflect | goals | forge | autonomy | webui"
        ),
    )
    args, command_args = p.parse_known_args()
    args.command_args = command_args
    if command_args and args.command not in {
        "skills",
        "tasks",
        "project",
        "learn",
        "reflect",
        "goals",
        "forge",
        "autonomy",
        "webui",
    }:
        p.error(f"unrecognized arguments: {' '.join(command_args)}")

    if args.command == "login":
        return _do_login(settings.normalize_provider(args.provider or settings.provider_default(saved)))
    if args.command == "logout":
        return _do_logout()
    if args.command == "setup":
        _do_setup(saved, args)
        return 0
    if args.command == "doctor":
        from core.doctor import run_doctor

        print(run_doctor(settings.resolve_workspace(args.cwd, saved)))
        return 0
    if args.command == "skills":
        return _do_skills(saved, args)
    if args.command == "tasks":
        return _do_tasks(saved, args)
    if args.command == "project":
        return _do_project(saved, args)
    if args.command == "learn":
        return _do_learn(saved, args)
    if args.command == "reflect":
        return _do_reflect(saved, args)
    if args.command == "goals":
        return _do_goals(saved, args)
    if args.command == "forge":
        return _do_forge(saved, args)
    if args.command == "autonomy":
        return _do_autonomy(saved, args)
    if args.command == "webui":
        return _do_webui(saved, args)
    if args.command == "bench":
        return _do_bench(saved, args)
    if args.command == "eval-target":
        return _do_eval_target(saved, args)
    if args.command == "app-daemon":
        from core.app_daemon import main as app_daemon_main

        return app_daemon_main(["--cwd", args.cwd] if args.cwd else [])
    did_setup = False
    if _needs_setup(saved, args):
        saved = _do_setup(saved, args)
        did_setup = True

    cwd = settings.resolve_workspace(args.cwd, saved)
    os.environ["CRYPT_ROOT"] = str(cwd)

    try:
        provider_name, model_override = _startup_choice(saved, args, skip=did_setup)
        cred = _credential(provider_name)
        cred = _login_if_needed(provider_name, cred, interactive=sys.stdin.isatty())
        if not _credential_is_usable(provider_name, cred):
            ui.error(_provider_missing_auth_message(provider_name))
            return 1
        provider = _provider(args, saved, provider_name, cred, model_override)
        _save_runtime_choice(args, saved, provider_name, provider.model, cwd)
        session_obj = _session_for_startup(args, cwd, provider)
        ui.clear_screen()
        _welcome(provider, cred, str(cwd), args, saved)

        def switch_model(active_provider):
            nonlocal saved, provider_name, model_override, cred, provider

            saved = settings.load_config()
            previous_provider_name = provider_name
            previous_model_override = model_override
            ui.info("switch provider/model")
            provider_name = _pick(
                "provider",
                [
                    (settings.PROVIDER_ANTHROPIC, "Anthropic OAuth"),
                    (settings.PROVIDER_OPENAI, "OpenAI (or compatible)"),
                    (settings.PROVIDER_CRYPT, "Crypt OAuth"),
                    (settings.PROVIDER_GEMINI, "Gemini OAuth/API key"),
                    (settings.PROVIDER_OLLAMA, "Ollama (local/cloud)"),
                ],
                getattr(active_provider, "name", provider_name),
            )
            host = settings.ollama_host(args.ollama_host, saved)
            model_override = _pick_model(provider_name, saved, host=host)
            if provider_name == settings.PROVIDER_OLLAMA:
                host = settings.ollama_host_for_model(model_override, host)
            if (
                provider_name == settings.PROVIDER_OLLAMA
                and settings.is_ollama_cloud_host(host)
                and not os.getenv("OLLAMA_API_KEY")
            ):
                ui.info("Ollama Cloud needs OLLAMA_API_KEY; Anthropic login is not used for Ollama")

            cred = _credential(provider_name)
            cred = _login_if_needed(provider_name, cred, interactive=sys.stdin.isatty())
            if not _credential_is_usable(provider_name, cred):
                ui.error(_provider_missing_auth_message(provider_name))
                provider_name = previous_provider_name
                model_override = previous_model_override
                return active_provider

            provider = _provider(args, saved, provider_name, cred, model_override)
            _save_runtime_choice(args, saved, provider_name, provider.model, Path(runtime.cwd()))
            ui.status_panel({
                "provider": provider.name,
                "model": provider.model,
                "auth": _provider_auth_label(provider_name, args, saved, cred, provider=provider),
                "approval": runtime.approval_label(),
            })
            return provider

        while True:
            result = run(
                provider,
                show_thinking=args.show_thinking,
                cwd=str(cwd),
                model_switcher=switch_model,
                session_obj=session_obj,
            )
            if result == "login":
                _do_login(provider_name)
            elif result == "logout":
                _do_logout()
            elif result == "model":
                provider = switch_model(provider)
                continue
            else:
                break

            cred = _credential(provider_name)
            if not _credential_is_usable(provider_name, cred):
                ui.error(_provider_missing_auth_message(provider_name))
                continue
            provider = _provider(args, settings.load_config(), provider_name, cred, model_override)
            ui.clear_screen()
            _welcome(provider, cred, str(cwd), args, settings.load_config())

    except KeyboardInterrupt:
        print()
        ui.info("interrupted")
        return 130
    except Exception as e:
        ui.error(f"{type(e).__name__}: {e}")
        if os.getenv("CRYPT_DEBUG_TRACEBACK"):
            import traceback

            traceback.print_exc()
        if os.getenv("CRYPT_PAUSE_ON_ERROR") and sys.stdin.isatty():
            input("Press Enter to exit...")
        return 1
    return 0


def _needs_setup(saved: dict, args: argparse.Namespace) -> bool:
    if args.provider or args.model or args.cwd or os.getenv("CRYPT_PROVIDER"):
        return False
    if not _env_truthy("CRYPT_REQUIRE_SETUP"):
        return False
    return not saved.get("provider") or not saved.get("workspace")


def _session_for_startup(args: argparse.Namespace, cwd: Path, provider) -> sessions.Session:
    query = args.session or ("latest" if args.resume else None)
    if query:
        info = sessions.find_session(cwd, query)
        if info:
            return sessions.load_session(
                info.cwd or str(cwd),
                info.session_id,
                provider=getattr(provider, "name", ""),
                model=getattr(provider, "model", ""),
            )
        ui.info(f"no matching session for {query!r}; starting a new one")
    return sessions.Session(
        cwd,
        provider=getattr(provider, "name", ""),
        model=getattr(provider, "model", ""),
    )


def _do_setup(saved: dict, args: argparse.Namespace) -> dict:
    ui.info("setup: choose workspace, provider, and model")
    workspace = _ask_workspace(args.cwd, saved)
    provider = settings.normalize_provider(args.provider) or _pick(
        "provider",
        [
            ("anthropic", "Anthropic OAuth"),
            ("openai", "OpenAI (or compatible)"),
            (settings.PROVIDER_CRYPT, "Crypt OAuth"),
            ("gemini", "Gemini OAuth/API key"),
            ("ollama", "Ollama (local/cloud)"),
        ],
        settings.provider_default(saved),
    )

    if provider == settings.PROVIDER_ANTHROPIC:
        model = args.model or _pick_model(provider, saved)
        values = {
            "workspace": str(workspace),
            "provider": provider,
            "anthropic_model": model,
        }
    elif provider == settings.PROVIDER_OPENAI:
        model = args.model or _pick_model(provider, saved)
        values = {
            "workspace": str(workspace),
            "provider": provider,
            "openai_model": model,
        }
        if not os.getenv("OPENAI_API_KEY"):
            ui.info("OPENAI_API_KEY is not set; set it before using OpenAI")
    elif provider == settings.PROVIDER_CRYPT:
        model = args.model or _pick_model(provider, saved)
        values = {
            "workspace": str(workspace),
            "provider": provider,
            "crypt_model": model,
        }
    elif provider == settings.PROVIDER_GEMINI:
        model = args.model or _pick_model(provider, saved)
        values = {
            "workspace": str(workspace),
            "provider": provider,
            "gemini_model": model,
        }
        if not os.getenv("GEMINI_API_KEY") and not auth.resolve_gemini():
            ui.info("Gemini needs GEMINI_API_KEY or Google OAuth (`python -m crypt login --provider gemini`)")
    else:
        host = settings.ollama_host(args.ollama_host, saved)
        model = args.model or _pick_model(provider, saved, host=host)
        host = settings.ollama_host_for_model(model, host)
        values = {
            "workspace": str(workspace),
            "provider": provider,
            "ollama_model": model,
            "ollama_host": host,
        }
        if settings.is_ollama_cloud_host(host) and not os.getenv("OLLAMA_API_KEY"):
            ui.info("Ollama Cloud needs OLLAMA_API_KEY; Anthropic login is not used for Ollama")

    new_saved = settings.update_config(**values)
    os.environ["CRYPT_ROOT"] = str(workspace)
    ui.info(f"saved setup in {settings.CONFIG_PATH}")

    if provider == settings.PROVIDER_ANTHROPIC and not auth.resolve_anthropic() and ui.ask("log in to Anthropic OAuth now?"):
        _do_login(provider)
    if (
        provider == settings.PROVIDER_CRYPT
        and not auth.resolve_crypt()
        and ui.ask("log in to Crypt now?")
    ):
        _do_login(provider)
    if (
        provider == settings.PROVIDER_GEMINI
        and not auth.resolve_gemini()
        and ui.ask("log in to Gemini with Google OAuth now?")
    ):
        if _do_login(provider) != 0:
            ui.info("Gemini setup is saved, but auth is not complete yet.")
    return new_saved


def _startup_choice(saved: dict, args: argparse.Namespace, skip: bool = False) -> tuple[str, str | None]:
    provider_name = settings.normalize_provider(args.provider) or settings.provider_default(saved)
    model_override = args.model
    first_run_no_config = not saved.get("provider") and not _env_truthy("CRYPT_PICKER")
    if skip or args.no_picker or args.provider or args.model or not sys.stdin.isatty() or first_run_no_config:
        return provider_name, model_override

    ui.info("choose provider and model")
    provider_name = _pick(
        "provider",
        [
            (settings.PROVIDER_ANTHROPIC, "Anthropic OAuth"),
            (settings.PROVIDER_OPENAI, "OpenAI (or compatible)"),
            (settings.PROVIDER_CRYPT, "Crypt OAuth"),
            (settings.PROVIDER_GEMINI, "Gemini OAuth/API key"),
            (settings.PROVIDER_OLLAMA, "Ollama (local/cloud)"),
        ],
        provider_name,
    )
    model_override = _pick_model(
        provider_name,
        saved,
        host=settings.ollama_host(args.ollama_host, saved),
    )
    return provider_name, model_override


def _ask_workspace(cli_root: str | None, saved: dict) -> Path:
    default = settings.resolve_workspace(cli_root, saved)
    raw = input(f"       workspace [{default}]: ").strip()
    path = Path(raw).expanduser() if raw else default
    path = path.resolve()
    if not path.exists():
        if ui.ask(f"create workspace {path}?"):
            path.mkdir(parents=True, exist_ok=True)
        else:
            return _ask_workspace(cli_root, saved)
    if not path.is_dir():
        ui.error(f"not a directory: {path}")
        return _ask_workspace(cli_root, saved)
    return path


def _pick(label: str, options: list[tuple[str, str]], default: str) -> str:
    default_idx = 1
    for i, (value, _) in enumerate(options, 1):
        if value == default:
            default_idx = i
            break
    return ui.splash_choice(label, options, default_idx)


def _pick_model(provider: str, saved: dict, *, host: str | None = None) -> str:
    if provider == settings.PROVIDER_ANTHROPIC:
        models = settings.ANTHROPIC_MODELS
    elif provider == settings.PROVIDER_OPENAI:
        models = settings.OPENAI_MODELS
    elif provider == settings.PROVIDER_CRYPT:
        models = settings.CRYPT_MODELS
    elif provider == settings.PROVIDER_GEMINI:
        models = settings.GEMINI_MODELS
    else:
        models = settings.OLLAMA_MODELS
    default = settings.model_default(provider, saved)
    options = [(m, m) for m in models]
    custom_value = "__custom__"
    if default not in models:
        options.insert(0, (default, f"{default} (saved custom)"))
    options.append((custom_value, "custom model id"))

    choice = _pick("model", options, default if default in [m for m, _ in options] else options[0][0])
    if choice != custom_value:
        return choice

    while True:
        raw = input("       model id: ").strip()
        if raw:
            return raw
        ui.error("model id cannot be empty")


def _credential(provider_name: str) -> auth.Credential | None:
    provider_name = settings.normalize_provider(provider_name)
    if provider_name == settings.PROVIDER_ANTHROPIC:
        return auth.resolve_anthropic()
    if provider_name == settings.PROVIDER_CRYPT:
        return auth.resolve_crypt()
    if provider_name == settings.PROVIDER_GEMINI:
        return auth.resolve_gemini()
    return None


def _credential_is_usable(provider_name: str, cred: auth.Credential | None) -> bool:
    provider_name = settings.normalize_provider(provider_name)
    if provider_name == settings.PROVIDER_ANTHROPIC:
        return cred is not None
    if provider_name == settings.PROVIDER_CRYPT:
        return bool(cred and cred.token and cred.account_id)
    if provider_name == settings.PROVIDER_GEMINI:
        if os.getenv("GEMINI_API_KEY"):
            return True
        return bool(cred and cred.token)
    return True


def _provider_missing_auth_message(provider_name: str) -> str:
    provider_name = settings.normalize_provider(provider_name)
    if provider_name == settings.PROVIDER_ANTHROPIC:
        return "Anthropic auth is missing; run `python main.py login --provider anthropic`."
    if provider_name == settings.PROVIDER_CRYPT:
        return "Crypt OAuth is missing or incomplete; run `python main.py login --provider crypt`."
    if provider_name == settings.PROVIDER_GEMINI:
        return (
            "Gemini auth is missing; set GEMINI_API_KEY or run "
            "`python main.py login --provider gemini`."
        )
    return "provider auth is missing"


def _login_prompt(provider_name: str, cred: auth.Credential | None) -> str | None:
    provider_name = settings.normalize_provider(provider_name)
    if provider_name == settings.PROVIDER_ANTHROPIC:
        return "log in to Anthropic OAuth now?"
    if provider_name == settings.PROVIDER_CRYPT:
        if cred:
            return "Crypt OAuth account id is missing; log in to Crypt again?"
        return "log in to Crypt now?"
    if provider_name == settings.PROVIDER_GEMINI:
        if cred and not cred.project_id:
            return "Gemini OAuth project id is missing; set GEMINI_PROJECT_ID and log in again?"
        return "log in to Gemini with Google OAuth now?"
    return None


def _login_if_needed(
    provider_name: str,
    cred: auth.Credential | None,
    *,
    interactive: bool = True,
) -> auth.Credential | None:
    if _credential_is_usable(provider_name, cred):
        return cred
    if not interactive:
        return cred

    prompt = _login_prompt(provider_name, cred)
    if not prompt:
        return cred

    if ui.ask(prompt):
        if _do_login(provider_name) == 0:
            return _credential(provider_name)
    return cred


def _env_truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _provider_auth_label(
    provider_name: str,
    args: argparse.Namespace | None,
    saved: dict | None,
    cred: auth.Credential | None,
    provider=None,
) -> str:
    provider_name = settings.normalize_provider(provider_name)
    if provider_name == settings.PROVIDER_ANTHROPIC:
        return cred.kind if cred else "missing Anthropic auth"
    if provider_name == settings.PROVIDER_OPENAI:
        return "OPENAI_API_KEY" if os.getenv("OPENAI_API_KEY") else "missing OPENAI_API_KEY"
    if provider_name == settings.PROVIDER_CRYPT:
        if cred:
            suffix = f" ({cred.email})" if cred.email else ""
            return f"Crypt OAuth{suffix}"
        return "missing Crypt OAuth"
    if provider_name == settings.PROVIDER_GEMINI:
        if os.getenv("GEMINI_API_KEY"):
            return "GEMINI_API_KEY"
        if cred:
            suffix = f" ({cred.email})" if cred.email else ""
            project = f" project={cred.project_id}" if cred.project_id else ""
            return f"Google OAuth{suffix}{project}"
        return "missing Gemini auth"

    host = getattr(provider, "_base_url", "") or settings.ollama_host(getattr(args, "ollama_host", None), saved or {})
    if settings.is_ollama_cloud_host(host):
        return "OLLAMA_API_KEY" if os.getenv("OLLAMA_API_KEY") else "missing OLLAMA_API_KEY"
    if settings.is_local_host(host):
        return "local Ollama"
    return "OLLAMA_API_KEY" if os.getenv("OLLAMA_API_KEY") else "default bearer token"


def _provider(
    args: argparse.Namespace,
    saved: dict,
    provider_name: str,
    cred: auth.Credential | None = None,
    model_override: str | None = None,
):
    provider_name = settings.normalize_provider(provider_name)
    if provider_name == settings.PROVIDER_ANTHROPIC:
        kwargs: dict = {
            "model": model_override or args.model or settings.model_default(provider_name, saved),
            "max_tokens": args.max_tokens or settings.env_int("ANTHROPIC_MAX_TOKENS", settings.ANTHROPIC_MAX_TOKENS),
            "thinking_budget": 0 if args.no_thinking else (
                args.thinking_budget
                or settings.env_int("ANTHROPIC_THINKING_BUDGET", settings.ANTHROPIC_THINKING_BUDGET)
            ),
        }
        if cred and cred.kind == "oauth":
            kwargs["auth_token"] = cred.token
        return AnthropicProvider(**kwargs)

    if provider_name == settings.PROVIDER_OPENAI:
        return OpenAIProvider(
            model=model_override or args.model or settings.model_default(provider_name, saved),
            max_tokens=args.max_tokens or settings.env_int("OPENAI_MAX_TOKENS", settings.OPENAI_MAX_TOKENS),
            base_url=settings.openai_base_url(saved),
            reasoning_effort=getattr(args, "reasoning_effort", None),
        )

    if provider_name == settings.PROVIDER_CRYPT:
        if not _credential_is_usable(provider_name, cred):
            raise RuntimeError(_provider_missing_auth_message(provider_name))
        return CryptProvider(
            model=model_override or args.model or settings.model_default(provider_name, saved),
            auth_token=cred.token,
            account_id=cred.account_id,
            max_tokens=args.max_tokens or settings.env_int(
                "CRYPT_MAX_TOKENS",
                settings.CRYPT_MAX_TOKENS,
            ),
            base_url=settings.crypt_base_url(saved),
            reasoning_effort=getattr(args, "reasoning_effort", None),
        )

    if provider_name == settings.PROVIDER_GEMINI:
        if not _credential_is_usable(provider_name, cred):
            raise RuntimeError(_provider_missing_auth_message(provider_name))
        return GeminiProvider(
            model=model_override or args.model or settings.model_default(provider_name, saved),
            auth_token=cred.token if cred and cred.kind == "oauth" else None,
            project_id=(cred.project_id if cred else None) or settings.gemini_project_id(saved),
            location=settings.gemini_vertex_location(saved),
            max_tokens=args.max_tokens or settings.env_int("GEMINI_MAX_TOKENS", settings.GEMINI_MAX_TOKENS),
            base_url=settings.gemini_base_url(saved),
        )

    host = settings.ollama_host(args.ollama_host, saved)
    model = model_override or args.model or settings.model_default(provider_name, saved)
    host = settings.ollama_host_for_model(model, host)
    return OllamaProvider(
        model=model,
        host=host,
        think=(not args.no_thinking and args.show_thinking),
        thinking_budget=getattr(args, "thinking_budget", None),
    )


def _do_skills(saved: dict, args: argparse.Namespace) -> int:
    from core import skill_manager

    parser = argparse.ArgumentParser(prog="crypt skills", description="manage local Crypt skills")
    sub = parser.add_subparsers(dest="action")
    list_p = sub.add_parser("list", help="list visible skills")
    list_p.add_argument("--enabled-only", action="store_true", help="hide blocked skills")
    add_p = sub.add_parser("add", aliases=["install"], help="install skills from a local folder or skills.sh source")
    add_p.add_argument("source", help="local path, GitHub owner/repo, git URL, or skills.sh source")
    add_p.add_argument("--skill", action="append", dest="skills", help="specific skill name; repeatable")
    add_p.add_argument("-g", "--global", action="store_true", dest="global_scope", help="install to ~/.crypt/skills")
    add_p.add_argument("--upstream-cli", action="store_true", help="force npx skills add even for local-looking sources")
    add_p.add_argument("-y", "--yes", action="store_true", help="pass yes through to the upstream skills CLI")
    rm_p = sub.add_parser("remove", aliases=["rm"], help="remove an installed Crypt skill")
    rm_p.add_argument("name", help="skill name")
    rm_p.add_argument("-g", "--global", action="store_true", dest="global_scope", help="remove from ~/.crypt/skills")
    parsed = parser.parse_args(args.command_args or ["list"])
    cwd = settings.resolve_workspace(args.cwd, saved)
    try:
        if parsed.action in (None, "list"):
            print(skill_manager.format_list(cwd, include_disabled=not parsed.enabled_only))
            return 0
        if parsed.action in ("add", "install"):
            print(
                skill_manager.install(
                    parsed.source,
                    cwd=cwd,
                    names=parsed.skills or [],
                    global_scope=parsed.global_scope,
                    use_upstream_cli=parsed.upstream_cli,
                    yes=parsed.yes,
                )
            )
            return 0
        if parsed.action in ("remove", "rm"):
            print(skill_manager.remove(parsed.name, cwd=cwd, global_scope=parsed.global_scope))
            return 0
    except Exception as e:
        ui.error(f"skills failed: {type(e).__name__}: {e}")
        return 1
    parser.print_help()
    return 1


def _do_tasks(saved: dict, args: argparse.Namespace) -> int:
    from core import task_state

    parser = argparse.ArgumentParser(prog="crypt tasks", description="inspect durable task logs")
    sub = parser.add_subparsers(dest="action")
    list_p = sub.add_parser("list", help="list recent tasks")
    list_p.add_argument("--all", action="store_true", help="list tasks from all workspaces")
    list_p.add_argument("--limit", type=int, default=12, help="maximum tasks to show")
    show_p = sub.add_parser("show", help="show one task event log")
    show_p.add_argument("task_id")
    show_p.add_argument("--tail", type=int, default=30)
    parsed = parser.parse_args(args.command_args or ["list"])
    cwd = settings.resolve_workspace(args.cwd, saved)
    if parsed.action in (None, "list"):
        print(task_state.format_task_list(cwd, all_projects=parsed.all, limit=parsed.limit))
        return 0
    if parsed.action == "show":
        print(task_state.format_task(cwd, parsed.task_id, tail=parsed.tail))
        return 0
    parser.print_help()
    return 1


def _do_project(saved: dict, args: argparse.Namespace) -> int:
    from core import project_index

    parser = argparse.ArgumentParser(prog="crypt project", description="inspect the Crypt project intelligence cache")
    parser.add_argument("--refresh", action="store_true", help="rescan the workspace before printing")
    parser.add_argument("--json", action="store_true", help="print the raw project profile as JSON")
    parsed = parser.parse_args(args.command_args or [])
    cwd = settings.resolve_workspace(args.cwd, saved)
    if parsed.json:
        import json
        from dataclasses import asdict

        profile = project_index.refresh(cwd) if parsed.refresh else project_index.get(cwd)
        print(json.dumps(asdict(profile), indent=2))
        return 0
    print(project_index.format_profile(cwd, refresh_first=parsed.refresh))
    return 0


def _do_learn(saved: dict, args: argparse.Namespace) -> int:
    from core import learning

    parser = argparse.ArgumentParser(prog="crypt learn", description="inspect Crypt's structured learning store")
    sub = parser.add_subparsers(dest="action")
    list_p = sub.add_parser("list", help="list learned lessons")
    list_p.add_argument("--limit", type=int, default=12)
    search_p = sub.add_parser("search", help="search lessons and prior task episodes")
    search_p.add_argument("query")
    search_p.add_argument("--limit", type=int, default=8)
    add_p = sub.add_parser("add", help="add an explicit learned lesson")
    add_p.add_argument("text")
    add_p.add_argument("--global", action="store_true", dest="global_scope")
    episodes_p = sub.add_parser("episodes", help="list prior learning episodes")
    episodes_p.add_argument("--query", default="")
    episodes_p.add_argument("--limit", type=int, default=12)
    parsed = parser.parse_args(args.command_args or ["list"])
    cwd = settings.resolve_workspace(args.cwd, saved)
    if parsed.action in (None, "list"):
        print(learning.format_lessons(cwd, limit=parsed.limit))
        return 0
    if parsed.action == "search":
        print(learning.format_lessons(cwd, query=parsed.query, limit=parsed.limit))
        print()
        print(learning.format_episodes(cwd, query=parsed.query, limit=parsed.limit))
        return 0
    if parsed.action == "add":
        lesson = learning.add_lesson(
            parsed.text,
            cwd=cwd,
            scope="global" if parsed.global_scope else "project",
            source="cli",
        )
        print(f"learned {lesson.lesson_id}: {lesson.text}")
        return 0
    if parsed.action == "episodes":
        print(learning.format_episodes(cwd, query=parsed.query, limit=parsed.limit))
        return 0
    parser.print_help()
    return 1


def _do_reflect(saved: dict, args: argparse.Namespace) -> int:
    from core import reflection

    parser = argparse.ArgumentParser(prog="crypt reflect", description="run or inspect Crypt self-reflection")
    parser.add_argument("action", nargs="?", choices=["list", "run"], default="list")
    parser.add_argument("--limit", type=int, default=5)
    parsed = parser.parse_args(args.command_args or [])
    cwd = settings.resolve_workspace(args.cwd, saved)
    if parsed.action == "run":
        created = reflection.reflect_recent(cwd, limit=parsed.limit)
        print("\n".join(f"{item.reflection_id}: {item.summary}" for item in created) or "no new episodes to reflect on")
        return 0
    print(reflection.format_reflections(cwd, limit=parsed.limit))
    return 0


def _do_goals(saved: dict, args: argparse.Namespace) -> int:
    from core import goals

    parser = argparse.ArgumentParser(prog="crypt goals", description="manage durable Crypt objectives")
    sub = parser.add_subparsers(dest="action")
    list_p = sub.add_parser("list")
    list_p.add_argument("--all", action="store_true")
    add_p = sub.add_parser("add")
    add_p.add_argument("title")
    add_p.add_argument("--description", default="")
    add_p.add_argument("--success", default="")
    add_p.add_argument("--cadence", default="")
    add_p.add_argument("--priority", type=int, default=3)
    update_p = sub.add_parser("update")
    update_p.add_argument("goal_id")
    update_p.add_argument("--status", choices=sorted(goals.STATUSES))
    update_p.add_argument("--last-result")
    parsed = parser.parse_args(args.command_args or ["list"])
    cwd = settings.resolve_workspace(args.cwd, saved)
    if parsed.action in (None, "list"):
        print(goals.format_goals(cwd, include_all=parsed.all))
        return 0
    if parsed.action == "add":
        goal = goals.add_goal(
            parsed.title,
            description=parsed.description,
            workspace=cwd,
            success_metric=parsed.success,
            cadence=parsed.cadence,
            priority=parsed.priority,
            tags=["cli"],
        )
        print(f"added {goal.goal_id}: {goal.title}")
        return 0
    if parsed.action == "update":
        goal = goals.update_goal(parsed.goal_id, status=parsed.status, last_result=parsed.last_result)
        print(f"updated {goal.goal_id}: {goal.status}")
        return 0
    parser.print_help()
    return 1


def _do_forge(saved: dict, args: argparse.Namespace) -> int:
    from core import skill_forge

    parser = argparse.ArgumentParser(prog="crypt forge", description="forge skills from learned lessons")
    parser.add_argument("topic", nargs="?", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--min-lessons", type=int, default=2)
    parsed = parser.parse_args(args.command_args or [])
    cwd = settings.resolve_workspace(args.cwd, saved)
    try:
        result = skill_forge.forge_skill(
            cwd,
            topic=parsed.topic,
            name=parsed.name,
            min_lessons=parsed.min_lessons,
        )
    except Exception as e:
        ui.error(f"forge failed: {type(e).__name__}: {e}")
        return 1
    print(skill_forge.format_result(result))
    return 0


def _do_autonomy(saved: dict, args: argparse.Namespace) -> int:
    from core import autonomy

    parser = argparse.ArgumentParser(prog="crypt autonomy", description="run or inspect safe autonomous learning")
    parser.add_argument("action", nargs="?", choices=["status", "run"], default="status")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--force-forge", action="store_true")
    parsed = parser.parse_args(args.command_args or [])
    cwd = settings.resolve_workspace(args.cwd, saved)
    if parsed.action == "run":
        cycle = autonomy.run_cycle(cwd, force_forge=parsed.force_forge, max_reflections=parsed.limit)
        print(f"{cycle.cycle_id}: reflected={cycle.reflected}, goals={cycle.goal_reviews}, lessons={cycle.lessons_added}")
        for note in cycle.notes:
            print(f"- {note}")
        return 0
    print(autonomy.format_cycles(cwd, limit=parsed.limit))
    return 0


def _do_webui(saved: dict, args: argparse.Namespace) -> int:
    from core import webui

    parser = argparse.ArgumentParser(prog="crypt webui", description="start the local Crypt WebUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the browser after starting")
    parsed = parser.parse_args(args.command_args or [])
    cwd = settings.resolve_workspace(args.cwd, saved)
    return webui.run(host=parsed.host, port=parsed.port, cwd=cwd, open_browser=parsed.open)


def _do_bench(saved: dict, args: argparse.Namespace) -> int:
    from core import bench

    suite = args.bench_suite or str(bench.DEFAULT_SUITE)
    if args.bench_list:
        print(bench.list_tasks(suite))
        return 0

    provider_name = settings.normalize_provider(args.provider) or settings.provider_default(saved)
    cred = _credential(provider_name)

    def provider_factory():
        return _provider(args, saved, provider_name, cred)

    try:
        report = bench.run_suite(
            provider_factory,
            suite_path=suite,
            output_root=args.bench_output,
            task_ids=args.bench_task,
            max_tasks=args.bench_max_tasks,
        )
    except Exception as e:
        ui.error(f"bench failed: {type(e).__name__}: {e}")
        return 1
    print(bench.format_report(report))
    return 0 if report.success else 1


def _do_eval_target(saved: dict, args: argparse.Namespace) -> int:
    from core import target_eval

    provider_name = settings.normalize_provider(args.provider) or settings.provider_default(saved)
    cred = _credential(provider_name)
    cwd = settings.resolve_workspace(args.cwd, saved)
    provider = _provider(args, saved, provider_name, cred)
    try:
        report = target_eval.run_target(
            provider,
            cwd=cwd,
            prompt=args.eval_prompt,
            checks=args.eval_check,
            output_root=args.eval_output,
            max_turns=args.eval_max_turns,
            forbidden_access=args.eval_forbid_access,
            cleanup=not args.eval_no_clean,
        )
    except Exception as e:
        ui.error(f"eval-target failed: {type(e).__name__}: {e}")
        return 1
    print(report.to_json() if args.eval_json else target_eval.format_report(report))
    return 0 if report.success else 1


def _save_runtime_choice(
    args: argparse.Namespace,
    saved: dict,
    provider_name: str,
    model: str,
    cwd: Path,
) -> None:
    provider_name = settings.normalize_provider(provider_name)
    values: dict[str, object] = {"provider": provider_name, "workspace": str(cwd)}
    if provider_name == settings.PROVIDER_ANTHROPIC:
        values["anthropic_model"] = model
    elif provider_name == settings.PROVIDER_OPENAI:
        values["openai_model"] = model
    elif provider_name == settings.PROVIDER_CRYPT:
        values["crypt_model"] = model
    elif provider_name == settings.PROVIDER_GEMINI:
        values["gemini_model"] = model
        project_id = settings.gemini_project_id(saved)
        if project_id:
            values["gemini_project_id"] = project_id
        location = settings.gemini_vertex_location(saved)
        if location:
            values["gemini_location"] = location
    else:
        values["ollama_model"] = model
        host = settings.ollama_host(args.ollama_host, saved)
        values["ollama_host"] = settings.ollama_host_for_model(model, host)
    settings.update_config(**values)


def _welcome(
    provider,
    cred: auth.Credential | None,
    cwd: str,
    args: argparse.Namespace | None = None,
    saved: dict | None = None,
) -> None:
    provider_name = getattr(provider, "name", "")
    ui.welcome(
        provider=provider.name,
        model=provider.model,
        auth_kind=_provider_auth_label(provider_name, args, saved, cred, provider=provider),
        auth_email=cred.email if provider_name in {settings.PROVIDER_ANTHROPIC, settings.PROVIDER_CRYPT, settings.PROVIDER_GEMINI} and cred else None,
        auth_plan=cred.plan if provider_name in {settings.PROVIDER_ANTHROPIC, settings.PROVIDER_CRYPT} and cred else None,
        cwd=cwd,
    )


def _do_login(provider_name: str = settings.PROVIDER_ANTHROPIC) -> int:
    provider_name = settings.normalize_provider(provider_name)
    try:
        now_ms = int(time.time() * 1000)
        if provider_name == settings.PROVIDER_CRYPT:
            from core.openai_oauth import login

            tokens = login(on_status=lambda m: ui.info(m))
            expires_in = tokens.get("expires_in", 3600)
            claims = tokens.get("claims") or {}
            auth.save_provider(settings.PROVIDER_CRYPT, {
                "type": settings.PROVIDER_CRYPT,
                "access": tokens["access_token"],
                "refresh": tokens.get("refresh_token"),
                "expires": now_ms + expires_in * 1000 - 5 * 60 * 1000,
                "account_id": tokens.get("account_id"),
                "email": claims.get("email"),
                "plan": tokens.get("plan"),
            })
            ui.info("logged in to Crypt")
        elif provider_name == settings.PROVIDER_GEMINI:
            from core.gemini_oauth import login

            tokens = login(on_status=lambda m: ui.info(m))
            auth.save_provider("gemini", {
                "type": "gemini-oauth",
                "credentials": tokens["credentials"],
                "project_id": tokens.get("project_id") or os.getenv("GEMINI_PROJECT_ID"),
            })
            ui.info("logged in to Gemini")
        else:
            from core.oauth import login

            tokens = login(on_status=lambda m: ui.info(m))
            expires_in = tokens.get("expires_in", 3600)
            auth.save_provider("anthropic", {
                "type": "oauth",
                "access": tokens["access_token"],
                "refresh": tokens.get("refresh_token"),
                "expires": now_ms + expires_in * 1000 - 5 * 60 * 1000,
            })
            ui.info("logged in")
        return 0
    except Exception as e:
        ui.error(f"login failed: {e}")
        return 1


def _do_logout() -> int:
    auth.delete()
    ui.info("logged out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
