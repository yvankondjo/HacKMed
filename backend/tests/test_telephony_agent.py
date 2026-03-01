import pytest

pytest.importorskip("livekit")

from agents.telephony_agent import (
    VoiceAssistant,
    load_agent_prompt,
    load_welcome_message,
    validate_required_env,
)


def test_load_agent_prompt_returns_non_empty_prompt() -> None:
    prompt = load_agent_prompt()
    assert isinstance(prompt, str)
    assert len(prompt.strip()) > 10


def test_load_welcome_message_defaults_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEPHONY_WELCOME_MESSAGE", raising=False)
    message = load_welcome_message()
    assert "MedVoice Care Connect" in message
    assert "first visit" in message


def test_load_welcome_message_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEPHONY_WELCOME_MESSAGE", "Hello test caller.")
    assert load_welcome_message() == "Hello test caller."


def test_validate_required_env_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(RuntimeError):
        validate_required_env()


def test_validate_required_env_passes_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LIVEKIT_URL", "wss://demo.livekit.cloud")
    monkeypatch.setenv("LIVEKIT_API_KEY", "abc")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "def")
    validate_required_env()


def test_voice_assistant_exposes_booking_tool() -> None:
    agent = VoiceAssistant()
    assert hasattr(agent, "book_consultation_with_confirmation")
    assert hasattr(agent, "load_patient_context_by_phone")
    assert hasattr(agent, "propose_consultation_slots")
