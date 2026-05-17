from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from backend.app.broker.zerodha_market_data import ZerodhaNotConfiguredError
from backend.app.broker.zerodha_session import ZerodhaSessionClient
from backend.app.core.config import settings
from backend.app.db.broker_sessions import (
    deactivate_zerodha_session,
    get_active_zerodha_session,
    save_zerodha_session,
)
from backend.app.db.session import get_db
from backend.app.schemas.zerodha import ZerodhaSessionRequest
from backend.app.services.instrument_sync import sync_zerodha_instruments
from backend.app.services.zerodha_stream import zerodha_stream_service

router = APIRouter(prefix="/zerodha", tags=["zerodha"])


@router.get("/status")
def zerodha_status(db: Session = Depends(get_db)) -> dict:
    trading_day = ZerodhaSessionClient.trading_day()
    active_session = get_active_zerodha_session(db, trading_day)
    status = ZerodhaSessionClient().status(
        active_token=active_session.access_token if active_session else None
    )
    status["trading_day"] = trading_day.isoformat()
    status["session_user"] = active_session.user_name if active_session else None
    return status


@router.get("/login-url")
def zerodha_login_url() -> dict:
    try:
        return {"login_url": ZerodhaSessionClient().login_url()}
    except ZerodhaNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/login")
def zerodha_login():
    try:
        return RedirectResponse(ZerodhaSessionClient().login_url())
    except ZerodhaNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("/callback")
def zerodha_callback(request_token: str, db: Session = Depends(get_db)):
    try:
        session = ZerodhaSessionClient().generate_session(request_token)
    except ZerodhaNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    broker_session = save_zerodha_session(
        db=db,
        access_token=session["access_token"],
        public_token=session.get("public_token"),
        user_id=session.get("user_id"),
        user_name=session.get("user_name"),
        trading_day=ZerodhaSessionClient.trading_day(),
    )
    try:
        sync_zerodha_instruments(db=db, exchange="NFO")
        return RedirectResponse(f"{settings.frontend_url}?zerodha=connected&sync=done")
    except Exception:
        return RedirectResponse(f"{settings.frontend_url}?zerodha=connected&sync=failed")


@router.post("/session")
def zerodha_session(payload: ZerodhaSessionRequest, db: Session = Depends(get_db)) -> dict:
    try:
        session = ZerodhaSessionClient().generate_session(payload.request_token)
    except ZerodhaNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    broker_session = save_zerodha_session(
        db=db,
        access_token=session["access_token"],
        public_token=session.get("public_token"),
        user_id=session.get("user_id"),
        user_name=session.get("user_name"),
        trading_day=ZerodhaSessionClient.trading_day(),
    )
    sync_result = None
    try:
        sync_result = sync_zerodha_instruments(db=db, exchange="NFO")
    except Exception as exc:
        sync_result = {"synced": 0, "error": str(exc)}
    return {
        "message": "Zerodha connected. Access token stored for today's trading session.",
        "session_id": broker_session.id,
        "trading_day": broker_session.trading_day.isoformat(),
        "user_id": session.get("user_id"),
        "user_name": session.get("user_name"),
        "instrument_sync": sync_result,
    }


@router.post("/logout")
def zerodha_logout(db: Session = Depends(get_db)) -> dict:
    deactivated = deactivate_zerodha_session(db, date.today())
    return {"deactivated": deactivated}


@router.post("/stream/start")
def zerodha_stream_start(db: Session = Depends(get_db)) -> dict:
    try:
        return zerodha_stream_service.start(db)
    except ZerodhaNotConfiguredError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/stream/stop")
def zerodha_stream_stop() -> dict:
    return zerodha_stream_service.stop()


@router.get("/stream/status")
def zerodha_stream_status() -> dict:
    return zerodha_stream_service.status()
