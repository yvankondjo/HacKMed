from agents.speechmatics_vocab import load_speechmatics_vocab_specs


def test_load_speechmatics_vocab_specs_from_email_hints(monkeypatch) -> None:
    monkeypatch.setenv("SPEECHMATICS_EMAIL_HINTS", "yvankondjo8@gmail.com")
    monkeypatch.delenv("SPEECHMATICS_ADDITIONAL_VOCAB", raising=False)

    specs = load_speechmatics_vocab_specs()
    contents = [item["content"] for item in specs]
    assert "yvankondjo8@gmail.com" in contents


def test_load_speechmatics_vocab_specs_from_csv(monkeypatch) -> None:
    monkeypatch.delenv("SPEECHMATICS_EMAIL_HINTS", raising=False)
    monkeypatch.setenv("SPEECHMATICS_ADDITIONAL_VOCAB", "gmail.com,outlook.com")

    specs = load_speechmatics_vocab_specs()
    contents = [item["content"] for item in specs]
    assert "gmail.com" in contents
    assert "outlook.com" in contents
