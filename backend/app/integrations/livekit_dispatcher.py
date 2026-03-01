from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class DispatchResult:
    status: str
    provider: str
    dispatch_id: str | None
    room_name: str | None
    detail: str | None = None


class LiveKitOutboundDispatcher:
    def __init__(
        self,
        *,
        livekit_url: str,
        api_key: str,
        api_secret: str,
        agent_name: str,
        sip_outbound_trunk_id: str | None = None,
    ) -> None:
        self._livekit_url = (livekit_url or "").strip()
        self._api_key = (api_key or "").strip()
        self._api_secret = (api_secret or "").strip()
        self._agent_name = (agent_name or "outbound-caller").strip()
        self._sip_outbound_trunk_id = (sip_outbound_trunk_id or "").strip()

    @property
    def enabled(self) -> bool:
        return bool(self._livekit_url and self._api_key and self._api_secret and self._agent_name)

    async def dispatch_followup_call(
        self,
        *,
        metadata: dict[str, Any],
        room_name: str | None = None,
        auto_dial: bool = False,
    ) -> DispatchResult:
        if not self.enabled:
            return DispatchResult(
                status="mock",
                provider="livekit-dispatch",
                dispatch_id=None,
                room_name=room_name,
                detail="Missing LiveKit credentials. Outbound dispatch is running in mock mode.",
            )

        try:
            from livekit import api as livekit_api  # type: ignore
            from livekit.protocol import agent_dispatch as agent_dispatch_proto  # type: ignore
            from livekit.protocol import room as room_proto  # type: ignore
            from livekit.protocol import sip as sip_proto  # type: ignore
        except Exception as exc:  # pragma: no cover
            return DispatchResult(
                status="failed",
                provider="livekit-dispatch",
                dispatch_id=None,
                room_name=room_name,
                detail=f"LiveKit SDK import failed: {exc}",
            )

        dispatch_room = (room_name or "").strip() or f"followup-{uuid4().hex[:10]}"
        api_url = self._livekit_url
        if api_url.startswith("wss://"):
            api_url = "https://" + api_url[6:]
        elif api_url.startswith("ws://"):
            api_url = "http://" + api_url[5:]

        lk = livekit_api.LiveKitAPI(
            url=api_url,
            api_key=self._api_key,
            api_secret=self._api_secret,
        )
        try:
            try:
                await lk.room.create_room(
                    room_proto.CreateRoomRequest(
                        name=dispatch_room,
                        empty_timeout=60 * 15,
                        departure_timeout=20,
                    )
                )
            except Exception as exc:
                text = str(exc).lower()
                if "already exists" not in text and "room already" not in text:
                    raise RuntimeError(f"Failed to ensure room '{dispatch_room}': {exc}") from exc

            request = agent_dispatch_proto.CreateAgentDispatchRequest(
                agent_name=self._agent_name,
                room=dispatch_room,
                metadata=json.dumps(metadata),
            )
            dispatch = await lk.agent_dispatch.create_dispatch(request)
            dispatch_id = str(
                getattr(dispatch, "id", None)
                or getattr(dispatch, "dispatch_id", None)
                or getattr(dispatch, "dispatchId", None)
                or ""
            ).strip() or None

            if auto_dial and self._sip_outbound_trunk_id:
                dial_to = str(metadata.get("dial_to") or "").strip()
                if dial_to:
                    sip_identity = f"sip-{uuid4().hex[:10]}"
                    await lk.sip.create_sip_participant(
                        sip_proto.CreateSIPParticipantRequest(
                            room_name=dispatch_room,
                            sip_trunk_id=self._sip_outbound_trunk_id,
                            sip_call_to=dial_to,
                            participant_identity=sip_identity,
                            participant_name=str(metadata.get("patient_name") or "Patient"),
                            wait_until_answered=False,
                        )
                    )

            return DispatchResult(
                status="queued",
                provider="livekit-dispatch",
                dispatch_id=dispatch_id,
                room_name=dispatch_room,
                detail=f"Dispatched agent '{self._agent_name}' at {datetime.now(timezone.utc).isoformat()}",
            )
        except Exception as exc:  # pragma: no cover
            return DispatchResult(
                status="failed",
                provider="livekit-dispatch",
                dispatch_id=None,
                room_name=dispatch_room,
                detail=str(exc),
            )
        finally:
            await lk.aclose()
