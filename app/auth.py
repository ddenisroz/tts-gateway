from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings


def _extract_token(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if raw.lower().startswith("bearer "):
        return raw[7:].strip() or None
    return raw


def verify_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    x_internal_service_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    allowed = settings.api_keys
    if not allowed:
        return
    token = _extract_token(authorization) or _extract_token(x_api_key) or _extract_token(x_internal_service_key)
    if token and token in allowed:
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
