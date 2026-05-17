from datetime import date
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.broker.zerodha_session import ZerodhaSessionClient
from backend.app.db.broker_sessions import get_active_zerodha_session
from backend.app.db.repositories import upsert_instrument
from backend.app.models.tables import AuditLog


def sync_zerodha_instruments(
    db: Session,
    exchange: Optional[str] = "NFO",
    limit: Optional[int] = None,
) -> Dict[str, int]:
    session = get_active_zerodha_session(db, date.today())
    client = ZerodhaSessionClient(access_token=session.access_token if session else None)._client()
    rows: List[dict] = client.instruments(exchange=exchange) if exchange else client.instruments()

    synced = 0
    for row in rows[:limit] if limit else rows:
        token = row.get("instrument_token")
        symbol = row.get("tradingsymbol") or row.get("name") or str(token)
        row_exchange = row.get("exchange") or exchange or ""
        if token is None or not row_exchange:
            continue
        upsert_instrument(
            db=db,
            symbol=symbol,
            exchange=row_exchange,
            instrument_token=int(token),
            lot_size=int(row.get("lot_size") or 1),
            tick_size=float(row.get("tick_size") or 0.05),
        )
        synced += 1

    db.add(
        AuditLog(
            event_type="ZERODHA_INSTRUMENT_SYNC",
            message=f"Synced {synced} instruments from Zerodha",
        )
    )
    db.commit()
    return {"synced": synced}
