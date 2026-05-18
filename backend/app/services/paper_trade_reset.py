from datetime import date, datetime, time
from typing import Dict

from sqlalchemy import delete, false, select
from sqlalchemy.orm import Session

from backend.app.models.tables import AuditLog, Order, Position


TRADE_AUDIT_EVENTS = {
    "PAPER_EXECUTION",
    "PAPER_EXECUTION_FAILED",
    "DUPLICATE_POSITION_BLOCKED",
    "RE_ENTRY_BLOCKED",
    "EOD_SQUARE_OFF",
    "EOD_SQUARE_OFF_SKIPPED",
    "BUY",
    "SELL",
    "TARGET_CHECKPOINT_REACHED",
    "UPDATE_TRAILING_STOPLOSS",
}


def reset_paper_trades_for_day(db: Session, trading_day: date) -> Dict[str, int]:
    day_start = datetime.combine(trading_day, time.min)
    day_end = datetime.combine(trading_day, time.max)
    position_ids = list(
        db.scalars(select(Position.id).where(Position.trading_day == trading_day)).all()
    )

    orders_result = db.execute(
        delete(Order).where(
            (Order.position_id.in_(position_ids) if position_ids else false())
            | ((Order.created_at >= day_start) & (Order.created_at <= day_end))
        )
    )
    positions_result = db.execute(delete(Position).where(Position.trading_day == trading_day))
    audit_result = db.execute(
        delete(AuditLog).where(
            AuditLog.event_type.in_(TRADE_AUDIT_EVENTS),
            AuditLog.created_at >= day_start,
            AuditLog.created_at <= day_end,
        )
    )
    db.commit()
    return {
        "orders_deleted": orders_result.rowcount or 0,
        "positions_deleted": positions_result.rowcount or 0,
        "audit_events_deleted": audit_result.rowcount or 0,
    }
