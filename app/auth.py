from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings

def _matches_api_key(token: str, allowed_keys: set[str]) -> bool:
    return any(hmac.compare_digest(token, allowed) for allowed in allowed_keys)


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
    settings: Settings = Depends(get_settings),
) -> None:
    token = _extract_token(authorization) or _extract_token(x_api_key)
    allowed = settings.api_keys
    if token and _matches_api_key(token, allowed):
        return
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
