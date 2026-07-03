"""SL No. numbering config — editable from the app's Settings screen.

Deliberately separate from the read-only .env config (server URL/token/etc
stay in .env — this one specifically needs to be changeable by office staff
without server access, e.g. a new prefix each financial year).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth import verify_token
from app.models import SlNoConfig, SlNoConfigOut
from app.services.sheets import _next_sl_no, _service, get_sl_no_config, set_sl_no_config

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _with_preview(config: dict) -> SlNoConfigOut:
    try:
        preview = _next_sl_no(_service(), **config)
    except Exception:
        # Sheet unreachable — fall back to a preview based on config alone
        # rather than failing the whole settings screen.
        preview = f"{config['prefix']}{config['start_number']:0{config['padding']}d}"
    return SlNoConfigOut(**config, next_preview=preview)


@router.get("/sl-no", response_model=SlNoConfigOut)
async def get_sl_no(_token: str = Depends(verify_token)):
    return _with_preview(get_sl_no_config())


@router.put("/sl-no", response_model=SlNoConfigOut)
async def update_sl_no(body: SlNoConfig, _token: str = Depends(verify_token)):
    set_sl_no_config(prefix=body.prefix, start_number=body.start_number, padding=body.padding)
    return _with_preview(get_sl_no_config())
