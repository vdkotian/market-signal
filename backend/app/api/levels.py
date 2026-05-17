from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.db.repositories import (
    LockedLevelSetError,
    create_daily_level_set,
    get_daily_level_set,
    list_daily_level_sets,
    lock_past_level_sets,
)
from backend.app.db.session import get_db
from backend.app.schemas.instruments import DailyLevelSetCreate, DailyLevelSetRead

router = APIRouter(prefix="/level-sets", tags=["level-sets"])


@router.post("", response_model=DailyLevelSetRead)
def add_level_set(payload: DailyLevelSetCreate, db: Session = Depends(get_db)):
    try:
        return create_daily_level_set(
            db=db,
            instrument_id=payload.instrument_id,
            trading_day=payload.trading_day,
            created_by=payload.created_by or "system",
            levels=[level.model_dump() for level in payload.levels],
        )
    except LockedLevelSetError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.get("", response_model=List[DailyLevelSetRead])
def get_level_sets(db: Session = Depends(get_db)):
    lock_past_level_sets(db, today=date.today())
    return list_daily_level_sets(db)


@router.get("/{level_set_id}", response_model=DailyLevelSetRead)
def get_level_set(level_set_id: int, db: Session = Depends(get_db)):
    try:
        return get_daily_level_set(db, level_set_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
