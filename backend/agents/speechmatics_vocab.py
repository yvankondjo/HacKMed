from __future__ import annotations

import json
import os
from typing import Any


def _split_csv(raw: str) -> list[str]:
    return [chunk.strip() for chunk in raw.split(",") if chunk.strip()]


def _parse_vocab_json(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []

    items: list[dict[str, Any]] = []
    for entry in data:
        if isinstance(entry, str):
            text = entry.strip()
            if text:
                items.append({"content": text})
            continue
        if isinstance(entry, dict):
            content = str(entry.get("content") or "").strip()
            if not content:
                continue
            sounds_like_raw = entry.get("sounds_like") or entry.get("soundsLike") or []
            sounds_like = [
                str(item).strip()
                for item in sounds_like_raw
                if str(item).strip()
            ] if isinstance(sounds_like_raw, list) else []
            item: dict[str, Any] = {"content": content}
            if sounds_like:
                item["sounds_like"] = sounds_like
            items.append(item)
    return items


def load_speechmatics_vocab_specs() -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []

    # Optional list of full email hints, e.g. "alice@example.com,bob@gmail.com".
    for email in _split_csv(os.getenv("SPEECHMATICS_EMAIL_HINTS", "")):
        spoken = email.replace("@", " at ").replace(".", " dot ")
        specs.append({"content": email, "sounds_like": [spoken]})

    # Optional custom vocab:
    # - JSON list: [{"content":"gmail.com","sounds_like":["g mail dot com"]}]
    # - CSV list: "gmail.com,outlook.com"
    raw_vocab = (os.getenv("SPEECHMATICS_ADDITIONAL_VOCAB") or "").strip()
    if raw_vocab:
        if raw_vocab.startswith("["):
            specs.extend(_parse_vocab_json(raw_vocab))
        else:
            specs.extend({"content": value} for value in _split_csv(raw_vocab))

    # Baseline domains that improve dictation for email spelling.
    if not raw_vocab and not os.getenv("SPEECHMATICS_EMAIL_HINTS"):
        specs.extend(
            [
                {"content": "gmail.com", "sounds_like": ["g mail dot com", "gmail dot com"]},
                {"content": "outlook.com", "sounds_like": ["out look dot com", "outlook dot com"]},
                {"content": "yahoo.com", "sounds_like": ["ya hoo dot com", "yahoo dot com"]},
                {"content": "hotmail.com", "sounds_like": ["hot mail dot com", "hotmail dot com"]},
                {"content": "icloud.com", "sounds_like": ["i cloud dot com", "icloud dot com"]},
            ]
        )

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in specs:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        key = content.lower()
        if key in seen:
            continue
        seen.add(key)
        sounds_like = item.get("sounds_like")
        if isinstance(sounds_like, list):
            normalized = [
                str(value).strip()
                for value in sounds_like
                if str(value).strip()
            ]
            deduped.append({"content": content, "sounds_like": normalized} if normalized else {"content": content})
        else:
            deduped.append({"content": content})
    return deduped


def build_additional_vocab(speechmatics_module: Any) -> list[Any]:
    specs = load_speechmatics_vocab_specs()
    if not specs:
        return []

    entry_cls = getattr(speechmatics_module, "AdditionalVocabEntry", None)
    if not entry_cls:
        return [item["content"] for item in specs]

    out: list[Any] = []
    for item in specs:
        content = item["content"]
        sounds_like = item.get("sounds_like") or []
        if not isinstance(sounds_like, list):
            sounds_like = []
        try:
            if sounds_like:
                out.append(entry_cls(content=content, sounds_like=sounds_like))
            else:
                out.append(entry_cls(content=content))
        except TypeError:
            # Fallback for potential older keyword naming.
            try:
                if sounds_like:
                    out.append(entry_cls(content=content, soundsLike=sounds_like))
                else:
                    out.append(entry_cls(content=content))
            except TypeError:
                out.append(content)
    return out
