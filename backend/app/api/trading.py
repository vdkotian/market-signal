from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.db.session import get_db
from backend.app.services.eod_square_off import square_off_open_positions

router = APIRouter(prefix="/trading", tags=["trading"])


@router.post("/eod-square-off")
def eod_square_off(db: Session = Depends(get_db)) -> dict:
    return square_off_open_positions(db, trading_day=date.today())
