from __future__ import annotations

from core import settings, smart_model_router


def test_smart_model_router_uses_fast_model_for_casual_chat():
    decision = smart_model_router.decide(
        "hey what is up",
        saved={"provider": settings.PROVIDER_CRYPT, "crypt_model": "crypt-max"},
    )

    assert decision.provider == settings.PROVIDER_CRYPT
    assert decision.model == "crypt-spark"
    assert decision.route_role == "fast"
    assert decision.reasoning == "low"
    assert decision.latency_bias == "fast"


def test_smart_model_router_uses_codex_for_code_work():
    decision = smart_model_router.decide(
        "fix the WebUI bug, update files, and run tests",
        saved={"provider": settings.PROVIDER_CRYPT},
    )

    assert decision.task_type == "code"
    assert decision.route_role == "builder"
    assert decision.model == "crypt-pro"
    assert decision.tool_need == "high"


def test_smart_model_router_escalates_all_out_requests():
    decision = smart_model_router.decide(
        "go all out and build the full autonomous business system perfectly",
        saved={"provider": settings.PROVIDER_CRYPT},
    )

    assert decision.model == "crypt-max"
    assert decision.reasoning == "max"
    assert decision.cost_bias == "quality"


def test_smart_model_router_maps_openai_reasoning_models():
    decision = smart_model_router.decide(
        "review this for security and architecture risk",
        saved={"provider": settings.PROVIDER_OPENAI},
    )

    assert decision.provider == settings.PROVIDER_OPENAI
    assert decision.model == "o3"
    assert decision.reasoning == "max"


def test_smart_model_router_prompt_section_is_available():
    section = smart_model_router.prompt_section({"provider": settings.PROVIDER_CRYPT})

    assert "# Smart Model Router V2" in section
    assert "configured provider" in section
