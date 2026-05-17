from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.enums import PositionStatus
from backend.app.db.session import get_db
from backend.app.market.tick_cache import tick_cache
from backend.app.models.tables import AuditLog, Order, Position

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)) -> dict:
    open_positions = list(
        db.scalars(select(Position).where(Position.status == PositionStatus.OPEN.value)).all()
    )
    orders = list(db.scalars(select(Order).order_by(Order.created_at.desc()).limit(20)).all())
    latest_ticks = tick_cache.latest()
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
                "side": order.side,
                "quantity": order.quantity,
                "price": order.price,
                "reason": order.reason,
                "created_at": order.created_at.isoformat(),
            }
            for order in orders
        ],
        "latest_prices": [
            {
                "instrument_id": tick.instrument_id,
                "instrument_token": tick.instrument_token,
                "symbol": tick.symbol,
                "last_price": tick.last_price,
                "timestamp": tick.timestamp.isoformat(),
            }
            for tick in latest_ticks.values()
        ],
        "audit_events": [
            {
                "event_type": event.event_type,
                "instrument_id": event.instrument_id,
                "message": event.message,
                "created_at": event.created_at.isoformat(),
            }
            for event in audit_events
        ],
    }


def _closed_positions(db: Session) -> List[Position]:
    return list(
        db.scalars(select(Position).where(Position.status == PositionStatus.CLOSED.value)).all()
    )
