from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.core.enums import LevelSetStatus
from backend.app.models.tables import AuditLog, DailyLevelSet, Instrument, Level


class LockedLevelSetError(ValueError):
    pass


class DuplicateLevelSetError(ValueError):
    pass


def create_instrument(
    db: Session,
    symbol: str,
    exchange: str,
    instrument_token: int,
    lot_size: int,
    tick_size: float,
) -> Instrument:
    instrument = Instrument(
        symbol=symbol,
        exchange=exchange,
        instrument_token=instrument_token,
        lot_size=lot_size,
        tick_size=tick_size,
    )
    db.add(instrument)
    db.commit()
    db.refresh(instrument)
    return instrument


def upsert_instrument(
    db: Session,
    symbol: str,
    exchange: str,
    instrument_token: int,
    lot_size: int,
    tick_size: float,
) -> Instrument:
    instrument = db.scalar(select(Instrument).where(Instrument.instrument_token == instrument_token))
    if instrument is None:
        instrument = Instrument(instrument_token=instrument_token)
    instrument.symbol = symbol
    instrument.exchange = exchange
    instrument.lot_size = lot_size
    instrument.tick_size = tick_size
    db.add(instrument)
    return instrument


def list_instruments(db: Session, query: Optional[str] = None, limit: int = 100) -> List[Instrument]:
    statement = select(Instrument).order_by(Instrument.symbol).limit(limit)
    if query:
        like_query = f"%{query.upper()}%"
        statement = (
            select(Instrument)
            .where(Instrument.symbol.ilike(like_query))
            .order_by(Instrument.symbol)
            .limit(limit)
        )
    return list(db.scalars(statement).all())


def get_instrument_by_token(db: Session, instrument_token: int) -> Instrument:
    instrument = db.scalar(select(Instrument).where(Instrument.instrument_token == instrument_token))
    if instrument is None:
        raise ValueError("Instrument not found")
    return instrument


def create_daily_level_set(
    db: Session,
    instrument_id: int,
    trading_day: date,
    created_by: str,
    levels: List[dict],
) -> DailyLevelSet:
    if trading_day < date.today():
        raise LockedLevelSetError("Past trading days cannot be edited")
    existing = db.scalar(
        select(DailyLevelSet).where(
            DailyLevelSet.instrument_id == instrument_id,
            DailyLevelSet.trading_day == trading_day,
            DailyLevelSet.status == LevelSetStatus.ACTIVE.value,
        )
    )
    if existing:
        raise DuplicateLevelSetError("Active level set already exists for instrument and day")

    level_set = DailyLevelSet(
        instrument_id=instrument_id,
        trading_day=trading_day,
        status=LevelSetStatus.ACTIVE.value,
        created_by=created_by,
        updated_by=created_by,
    )
    for level in levels:
        level_set.levels.append(Level(**level))

    db.add(level_set)
    db.add(
        AuditLog(
            event_type="DAILY_LEVEL_SET_CREATED",
            instrument_id=instrument_id,
            message=f"Created levels for {trading_day}",
        )
    )
    db.commit()
    db.refresh(level_set)
    return level_set


def ensure_demo_level_set(
    db: Session,
    trading_day: date,
    instrument_token: int = 900001,
) -> Instrument:
    instrument = db.scalar(select(Instrument).where(Instrument.instrument_token == instrument_token))
    if instrument is None:
        instrument = create_instrument(
            db=db,
            symbol="DEMO_NIFTY_CE",
            exchange="NFO",
            instrument_token=instrument_token,
            lot_size=1,
            tick_size=0.05,
        )

    existing = db.scalar(
        select(DailyLevelSet).where(
            DailyLevelSet.instrument_id == instrument.id,
            DailyLevelSet.trading_day == trading_day,
            DailyLevelSet.status == LevelSetStatus.ACTIVE.value,
        )
    )
    if existing:
        return instrument

    create_daily_level_set(
        db=db,
        instrument_id=instrument.id,
        trading_day=trading_day,
        created_by="simulation",
        levels=[
            {"level_name": "L0", "price": 100, "sort_order": 0, "role": "STOPLOSS"},
            {"level_name": "L1", "price": 110, "sort_order": 1, "role": "ENTRY"},
            {"level_name": "L2", "price": 120, "sort_order": 2, "role": "CHECKPOINT"},
            {"level_name": "L3", "price": 130, "sort_order": 3, "role": "CHECKPOINT"},
        ],
    )
    return instrument


def get_daily_level_set(db: Session, level_set_id: int) -> DailyLevelSet:
    level_set = db.scalar(
        select(DailyLevelSet)
        .options(selectinload(DailyLevelSet.levels))
        .where(DailyLevelSet.id == level_set_id)
    )
    if level_set is None:
        raise ValueError("Daily level set not found")
    return level_set


def list_daily_level_sets(db: Session) -> List[DailyLevelSet]:
    return list_daily_level_sets_filtered(db)


def list_daily_level_sets_filtered(
    db: Session,
    trading_day: Optional[date] = None,
    instrument_id: Optional[int] = None,
) -> List[DailyLevelSet]:
    statement = select(DailyLevelSet).options(selectinload(DailyLevelSet.levels))
    if trading_day:
        statement = statement.where(DailyLevelSet.trading_day == trading_day)
    if instrument_id:
        statement = statement.where(DailyLevelSet.instrument_id == instrument_id)
    statement = statement.order_by(DailyLevelSet.trading_day.desc(), DailyLevelSet.id.desc())
    return list(db.scalars(statement).all())


def update_daily_level_set(
    db: Session,
    level_set_id: int,
    updated_by: str,
    levels: List[dict],
) -> DailyLevelSet:
    level_set = get_daily_level_set(db, level_set_id)
    assert_level_set_editable(level_set, date.today())
    level_set.levels.clear()
    db.flush()
    for level in levels:
        level_set.levels.append(Level(**level))
    level_set.updated_by = updated_by
    db.add(
        AuditLog(
            event_type="DAILY_LEVEL_SET_UPDATED",
            instrument_id=level_set.instrument_id,
            message=f"Updated levels for {level_set.trading_day}",
        )
    )
    db.commit()
    db.refresh(level_set)
    return level_set


def cancel_daily_level_set(db: Session, level_set_id: int, updated_by: str) -> DailyLevelSet:
    level_set = get_daily_level_set(db, level_set_id)
    assert_level_set_editable(level_set, date.today())
    level_set.status = LevelSetStatus.CANCELLED.value
    level_set.updated_by = updated_by
    db.add(
        AuditLog(
            event_type="DAILY_LEVEL_SET_CANCELLED",
            instrument_id=level_set.instrument_id,
            message=f"Cancelled levels for {level_set.trading_day}",
        )
    )
    db.commit()
    db.refresh(level_set)
    return level_set


def lock_past_level_sets(db: Session, today: date) -> int:
    level_sets = db.scalars(
        select(DailyLevelSet).where(
            DailyLevelSet.trading_day < today,
            DailyLevelSet.status.in_([LevelSetStatus.DRAFT.value, LevelSetStatus.ACTIVE.value]),
        )
    ).all()
    for level_set in level_sets:
        level_set.status = LevelSetStatus.LOCKED.value
        level_set.locked_at = datetime.utcnow()
        db.add(
            AuditLog(
                event_type="DAILY_LEVEL_SET_LOCKED",
                instrument_id=level_set.instrument_id,
                message=f"Locked levels for {level_set.trading_day}",
            )
        )
    db.commit()
    return len(level_sets)


def assert_level_set_editable(level_set: DailyLevelSet, today: date) -> None:
    if level_set.trading_day < today or level_set.status == LevelSetStatus.LOCKED.value:
        raise LockedLevelSetError("Past or locked level sets cannot be edited")
