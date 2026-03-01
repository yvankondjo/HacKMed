import pytest

pytest.importorskip("livekit")

from agents.consultation_agent import (
    _infer_participant_role,
    _infer_role_from_text,
    _normalize_role,
    _parse_speaker_tag,
)


class _ParticipantStub:
    def __init__(
        self,
        identity: str = "",
        name: str = "",
        metadata: str = "",
        attributes: dict[str, str] | None = None,
    ) -> None:
        self.identity = identity
        self.name = name
        self.metadata = metadata
        self.attributes = attributes or {}


def test_normalize_role() -> None:
    assert _normalize_role("Doctor") == "doctor"
    assert _normalize_role("patient") == "patient"
    assert _normalize_role("something-else") == "unknown"


def test_infer_role_from_text() -> None:
    assert _infer_role_from_text("doc-123") == "doctor"
    assert _infer_role_from_text("patient-main") == "patient"
    assert _infer_role_from_text("visitor") == "unknown"


def test_infer_participant_role_prefers_attribute() -> None:
    participant = _ParticipantStub(
        identity="user-1",
        name="Unknown",
        attributes={"role": "doctor"},
    )
    assert _infer_participant_role(participant) == "doctor"


def test_parse_speaker_tag() -> None:
    speaker_id, clean = _parse_speaker_tag("<S2>hello there</S2>")
    assert speaker_id == "S2"
    assert clean == "hello there"
