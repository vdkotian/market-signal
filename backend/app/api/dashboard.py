from datetime import date
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from backend.app.core.enums import LevelSetStatus, PositionStatus
from backend.app.core.timezone import display_ist_time, iso_utc
from backend.app.db.session import get_db
from backend.app.market.tick_cache import tick_cache
from backend.app.models.tables import AuditLog, DailyLevelSet, Instrument, Order, Position

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)) -> dict:
    open_positions = list(
        db.scalars(select(Position).where(Position.status == PositionStatus.OPEN.value)).all()
    )
    orders = list(db.scalars(select(Order).order_by(Order.created_at.desc()).limit(20)).all())
    order_instrument_ids = {order.instrument_id for order in orders}
    order_instruments = {
        instrument.id: instrument
        for instrument in db.scalars(
            select(Instrument).where(Instrument.id.in_(order_instrument_ids))
        ).all()
    } if order_instrument_ids else {}
    latest_ticks = tick_cache.latest()
    active_level_sets = list(
        db.scalars(
            select(DailyLevelSet)
            .options(selectinload(DailyLevelSet.instrument), selectinload(DailyLevelSet.levels))
            .where(
                DailyLevelSet.trading_day == date.today(),
                DailyLevelSet.status == LevelSetStatus.ACTIVE.value,
            )
            .order_by(DailyLevelSet.id.desc())
        ).all()
    )
    audit_events = list(
        db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(20)).all()
    )

    realized_pnl = sum(position.realized_pnl or 0 for position in _closed_positions(db))
    unrealized_risk_locked = sum(
        (position.trailing_stoploss_price - position.entry_price) * position.quantity
        for position in open_positions
    )

    return {
        "counts": {
            "open_positions": len(open_positions),
            "recent_orders": len(orders),
            "latest_prices": len(latest_ticks),
            "tracked_instruments": len(active_level_sets),
            "audit_events": len(audit_events),
        },
        "pnl": {
            "realized": realized_pnl,
            "open_trailing_locked": unrealized_risk_locked,
        },
        "open_positions": [
            {
                "id": position.id,
                "instrument_id": position.instrument_id,
                "trading_day": position.trading_day.isoformat(),
                "quantity": position.quantity,
                "entry_price": position.entry_price,
                "stoploss_price": position.stoploss_price,
                "trailing_stoploss_price": position.trailing_stoploss_price,
                "high_water_mark": position.high_water_mark,
                "status": position.status,
            }
            for position in open_positions
        ],
        "orders": [
            {
                "id": order.id,
                "instrument_id": order.instrument_id,
                "symbol": order_instruments[order.instrument_id].symbol
                if order.instrument_id in order_instruments
                else f"#{order.instrument_id}",
                "exchange": order_instruments[order.instrument_id].exchange
                if order.instrument_id in order_instruments
                else "",
                "side": order.side,
                "quantity": order.quantity,
                "price": order.price,
                "reason": order.reason,
                "created_at": iso_utc(order.created_at),
                "created_at_ist": display_ist_time(order.created_at),
            }
            for order in orders
        ],
        "latest_prices": [
            {
                "instrument_id": tick.instrument_id,
                "instrument_token": tick.instrument_token,
                "symbol": tick.symbol,
                "last_price": tick.last_price,
                "timestamp": iso_utc(tick.timestamp),
                "timestamp_ist": display_ist_time(tick.timestamp),
            }
            for tick in latest_ticks.values()
        ],
        "tracked_instruments": [
            {
                "level_set_id": level_set.id,
                "instrument_id": level_set.instrument_id,
                "instrument_token": level_set.instrument.instrument_token,
                "symbol": level_set.instrument.symbol,
                "exchange": level_set.instrument.exchange,
                "last_price": latest_ticks[level_set.instrument_id].last_price
                if level_set.instrument_id in latest_ticks
                else None,
                "last_tick_at": iso_utc(latest_ticks[level_set.instrument_id].timestamp)
                if level_set.instrument_id in latest_ticks
                else None,
                "last_tick_at_ist": display_ist_time(latest_ticks[level_set.instrument_id].timestamp)
                if level_set.instrument_id in latest_ticks
                else None,
                "levels": [
                    {
                        "level_name": level.level_name,
                        "price": level.price,
                        "sort_order": level.sort_order,
                        "role": level.role,
                    }
                    for level in level_set.levels
                ],
            }
            for level_set in active_level_sets
        ],
        "audit_events": [
            {
                "event_type": event.event_type,
                "instrument_id": event.instrument_id,
                "message": event.message,
                "created_at": iso_utc(event.created_at),
                "created_at_ist": display_ist_time(event.created_at),
            }
            for event in audit_events
        ],
    }


def _closed_positions(db: Session) -> List[Position]:
    return list(
        db.scalars(select(Position).where(Position.status == PositionStatus.CLOSED.value)).all()
    )
