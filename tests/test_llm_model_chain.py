"""Tests for model fallback chain configuration."""

from enrichment_api.llm import _model_chain


def test_model_chain_deduplicates_and_keeps_order(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    monkeypatch.setenv(
        "ANTHROPIC_FALLBACK_MODELS",
        "claude-opus-4-6, claude-sonnet-4-20250514, claude-opus-4-6, custom-model",
    )

    assert _model_chain() == [
        "claude-sonnet-4-20250514",
        "claude-opus-4-6",
        "custom-model",
    ]


def test_model_chain_uses_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    monkeypatch.delenv("ANTHROPIC_FALLBACK_MODELS", raising=False)

    assert _model_chain() == ["claude-sonnet-4-20250514", "claude-opus-4-6"]
