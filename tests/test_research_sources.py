from __future__ import annotations

from core import research_sources, settings


def test_research_sources_save_search_and_limit_quotes(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()

    source = research_sources.add_source(
        workspace,
        url="https://example.com/report",
        title="Market Report",
        summary="Local business demand and lead generation stats.",
        quotes=["one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty twentyone twentytwo twentythree twentyfour twentyfive twentysix"],
        trust="trusted",
        tags=["business", "leads"],
    )

    assert source.trust == "trusted"
    assert len(source.quotes[0].split()) == 25
    hits = research_sources.search(workspace, "lead generation")
    assert hits[0].source_id == source.source_id
    assert "Research Sources" in research_sources.prompt_section(workspace, "lead generation")


def test_research_sources_observe_urls_and_dedupe(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "APP_DIR", tmp_path / "crypt-home")
    workspace = tmp_path / "repo"
    workspace.mkdir()
    text = "Read https://example.com/a and also https://example.com/a"

    rows = research_sources.observe_text(workspace, text)

    assert len(rows) == 2
    assert research_sources.snapshot(workspace)["total"] == 1
