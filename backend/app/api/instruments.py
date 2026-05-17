from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.app.db.repositories import create_instrument, list_instruments
from backend.app.db.session import get_db
from backend.app.schemas.instruments import InstrumentCreate, InstrumentRead
from backend.app.services.instrument_sync import sync_zerodha_instruments

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.post("", response_model=InstrumentRead)
def add_instrument(payload: InstrumentCreate, db: Session = Depends(get_db)):
    return create_instrument(
        db=db,
        symbol=payload.symbol,
        exchange=payload.exchange,
        instrument_token=payload.instrument_token,
        lot_size=payload.lot_size,
        tick_size=payload.tick_size,
    )


@router.get("", response_model=List[InstrumentRead])
def get_instruments(
    query: str = "",
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_instruments(db, query=query or None, limit=limit)


@router.post("/sync/zerodha")
def sync_instruments_from_zerodha(
    exchange: str = "NFO",
    limit: int = Query(default=0, ge=0, le=100000),
    db: Session = Depends(get_db),
) -> dict:
    try:
        return sync_zerodha_instruments(
            db=db,
            exchange=exchange or None,
            limit=limit or None,
        )
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc))
