from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import escape
from typing import Any
from urllib import error, request

# Direct email pattern.
_EMAIL_RE = re.compile(
    r"[a-z0-9][a-z0-9._%+\-]{0,63}@[a-z0-9][a-z0-9.\-]{1,253}\.[a-z]{2,24}",
    re.IGNORECASE,
)

logger = logging.getLogger("medvoice.resend")


@dataclass(frozen=True)
class ResendResult:
    ok: bool
    status: str
    message_id: str | None
    to: str | None
    detail: str | None = None


def _env(*names: str, default: str | None = None) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return default


def extract_email_from_text(text: str) -> str | None:
    raw = (text or "").strip()
    if not raw:
        return None

    direct = [m.group(0).strip(".,;:!?").lower() for m in _EMAIL_RE.finditer(raw)]
    if direct:
        return direct[0]

    # Spoken variants: "john at gmail dot com", "john arobase gmail point com".
    normalized = raw.lower()
    replacements = (
        (r"\barobase\b", "@"),
        (r"\bat\b", "@"),
        (r"\bpoint\b", "."),
        (r"\bdot\b", "."),
        (r"\bunderscore\b", "_"),
        (r"\bdash\b", "-"),
        (r"\bhyphen\b", "-"),
        (r"\bplus\b", "+"),
    )
    for pattern, value in replacements:
        normalized = re.sub(pattern, value, normalized)
    normalized = re.sub(r"\s*@\s*", "@", normalized)
    normalized = re.sub(r"\s*\.\s*", ".", normalized)
    normalized = re.sub(r"\s*_\s*", "_", normalized)
    normalized = re.sub(r"\s*-\s*", "-", normalized)
    normalized = re.sub(r"\s*\+\s*", "+", normalized)

    guess = _EMAIL_RE.search(normalized)
    if guess:
        return guess.group(0).strip(".,;:!?").lower()
    return None


def extract_email_from_transcript(transcript: list[dict[str, Any]]) -> str | None:
    for item in transcript:
        email = extract_email_from_text(str(item.get("text") or ""))
        if email:
            return email
    return None


def build_prescription_template(
    *,
    patient_name: str,
    doctor_name: str,
    appointment_id: str,
    medications: list[dict[str, Any]],
    additional_advice: list[str] | None = None,
) -> tuple[str, str]:
    issued_at = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    safe_patient = escape(patient_name or "Patient")
    safe_doctor = escape(doctor_name or "Doctor")
    safe_appointment = escape(appointment_id or "unknown")

    med_rows: list[str] = []
    text_rows: list[str] = []
    for med in medications:
        name = escape(str(med.get("name") or "Medication").strip())
        dosage = escape(str(med.get("dosage") or "").strip())
        frequency = escape(str(med.get("frequency") or "").strip())
        duration = escape(str(med.get("duration") or "").strip())
        details = " | ".join([x for x in (dosage, frequency, duration) if x]) or "As prescribed."
        med_rows.append(
            f"<div class='med-item'><p class='med-name'>{name}</p><p class='med-details'>{details}</p></div>"
        )
        text_rows.append(f"- {name}: {details}")

    if not med_rows:
        med_rows.append("<div class='med-item'><p class='med-name'>No medication listed</p></div>")
        text_rows.append("- No medication listed")

    advice_items: list[str] = []
    text_advice: list[str] = []
    for line in additional_advice or []:
        clean = str(line or "").strip()
        if not clean:
            continue
        advice_items.append(f"<li>{escape(clean)}</li>")
        text_advice.append(f"- {clean}")

    advice_html = f"<ul>{''.join(advice_items)}</ul>" if advice_items else "<p>No additional advice.</p>"

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Ordonnance</title>
  <style>
    body {{ margin:0; padding:24px; background:#f2f4f8; color:#101320; font-family:Arial, Helvetica, sans-serif; }}
    .sheet {{ max-width:760px; margin:0 auto; background:#fff; border:1px solid #d9dde7; border-radius:10px; padding:28px; }}
    .header {{ text-align:center; border-bottom:1px solid #e6e8ef; margin-bottom:18px; padding-bottom:12px; }}
    .header h1 {{ margin:8px 0 0 0; font-size:34px; }}
    .meta {{ display:flex; gap:12px; margin-bottom:18px; }}
    .box {{ flex:1; border:1px solid #e6e8ef; border-radius:8px; padding:10px 12px; font-size:14px; }}
    .med-item {{ margin:0 0 14px 0; }}
    .med-name {{ margin:0; font-size:17px; font-weight:700; }}
    .med-details {{ margin:4px 0 0 0; color:#2d3a4d; font-size:14px; }}
    .signature {{ margin-top:26px; text-align:right; }}
    .signature .line {{ border-top:1px solid #111; display:inline-block; width:230px; margin-top:30px; padding-top:6px; text-align:center; }}
    .footer {{ margin-top:24px; border-top:1px solid #e6e8ef; padding-top:10px; color:#445066; font-size:12px; }}
  </style>
</head>
<body>
  <div class="sheet">
    <div class="header">
      <div style="font-size:14px;font-weight:600;">MedVoice Care Connect</div>
      <div style="font-size:12px;color:#4f5b70;">Auto-generated prescription</div>
      <h1>Ordonnance</h1>
    </div>
    <div class="meta">
      <div class="box">
        <strong>Patient</strong><br />
        {safe_patient}<br />
        Appointment: {safe_appointment}<br />
        Issued: {escape(issued_at)}
      </div>
      <div class="box">
        <strong>Doctor</strong><br />
        {safe_doctor}
      </div>
    </div>
    {''.join(med_rows)}
    <div>
      <strong>Additional Advice</strong>
      {advice_html}
    </div>
    <div class="signature">
      <div class="line">{safe_doctor}</div>
    </div>
    <div class="footer">
      Medical information intended only for the recipient.
    </div>
  </div>
</body>
</html>
"""

    text = "\n".join(
        [
            "ORDONNANCE - MedVoice Care Connect",
            f"Patient: {patient_name or 'Patient'}",
            f"Doctor: {doctor_name or 'Doctor'}",
            f"Appointment: {appointment_id}",
            f"Issued: {issued_at}",
            "",
            "Medications:",
            *text_rows,
            "",
            "Additional Advice:",
            *(text_advice or ["- No additional advice."]),
        ]
    )

    return html, text


def send_with_resend(
    *,
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
) -> ResendResult:
    api_key = _env("RESEND_API_KEY", "resend_api_key", "RENSEND_API_KEY", "rensend_api_key")
    from_email = _env("RESEND_FROM_EMAIL", "resend_from_email", default="onboarding@resend.dev")
    reply_to = _env("RESEND_REPLY_TO", "resend_reply_to")
    override_to = _env("RESEND_TO", "resend_to", default="yvankondjo8@gmail.com")
    actual_to = override_to if override_to else to_email

    if not api_key:
        logger.error("Missing RESEND_API_KEY; email sending is disabled.")
        return ResendResult(ok=False, status="disabled", message_id=None, to=actual_to, detail="Missing RESEND_API_KEY")

    payload: dict[str, Any] = {
        "from": from_email,
        "to": [actual_to],
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    if reply_to:
        payload["reply_to"] = reply_to

    logger.info("Sending prescription email via Resend to=%s from=%s", actual_to, from_email)

    req = request.Request(
        url="https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "MedVoice/1.0")

    try:
        with request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8")
        parsed = json.loads(body) if body else {}
        message_id = str(parsed.get("id") or "")
        logger.info("Resend accepted message id=%s", message_id)
        return ResendResult(ok=True, status="sent", message_id=message_id or None, to=actual_to, detail=None)
    except error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        logger.error("Resend HTTP error status=%s detail=%s", exc.code, detail[:500])
        return ResendResult(ok=False, status="failed", message_id=None, to=actual_to, detail=detail[:500])
    except Exception as exc:
        logger.exception("Resend send failed: %s", exc)
        return ResendResult(ok=False, status="failed", message_id=None, to=actual_to, detail=str(exc))


def send_prescription_to_patient(
    *,
    transcript: list[dict[str, Any]],
    patient_name: str,
    doctor_name: str,
    appointment_id: str,
    medications: list[dict[str, Any]],
    patient_email: str | None = None,
    additional_advice: list[str] | None = None,
) -> ResendResult:
    recipient = (patient_email or "").strip() or extract_email_from_transcript(transcript)
    if not recipient:
        return ResendResult(ok=False, status="skipped", message_id=None, to=None, detail="No email found in transcript")

    html, text = build_prescription_template(
        patient_name=patient_name,
        doctor_name=doctor_name,
        appointment_id=appointment_id,
        medications=medications,
        additional_advice=additional_advice or [],
    )
    subject = f"Ordonnance - {patient_name} - {datetime.now(timezone.utc).strftime('%d/%m/%Y')}"
    logger.info("Preparing prescription email for patient=%s appointment=%s target=%s", patient_name, appointment_id, recipient)
    return send_with_resend(
        to_email=recipient,
        subject=subject,
        html_body=html,
        text_body=text,
    )
