from datetime import date
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.app.broker.zerodha_market_data import (
    ZerodhaMarketDataClient,
    ZerodhaNotConfiguredError,
)
from backend.app.core.config import TradingMode, settings
from backend.app.db.broker_sessions import get_active_zerodha_session
from backend.app.db.session import SessionLocal
from backend.app.db.trading_state import (
    get_active_instrument_token_map,
    validate_active_level_sets,
)
from backend.app.dto.trading_dto import Tick
from backend.app.services.tick_processor import process_tick


class ZerodhaStreamService:
    def __init__(self) -> None:
        self.running = False
        self.instrument_tokens: List[int] = []
        self.last_error: Optional[str] = None
        self.processed_ticks = 0
        self.client = None

    def status(self) -> Dict[str, object]:
        return {
            "running": self.running,
            "instrument_tokens": self.instrument_tokens,
            "processed_ticks": self.processed_ticks,
            "last_error": self.last_error,
        }

    def start(
        self,
        db: Session,
        client_factory: Callable[[Dict[int, int], str], ZerodhaMarketDataClient] = ZerodhaMarketDataClient,
    ) -> Dict[str, object]:
        if self.running:
            return self.status()

        if settings.trading_mode != TradingMode.PAPER:
            raise ZerodhaNotConfiguredError("Zerodha stream is allowed only in PAPER mode")
        if settings.enable_live_trading:
            raise ZerodhaNotConfiguredError("Refusing stream start while live trading is enabled")

        trading_day = date.today()
        session = get_active_zerodha_session(db, trading_day)
        if not session:
            raise ZerodhaNotConfiguredError("No active Zerodha session for today")

        token_map = get_active_instrument_token_map(db, trading_day)
        if not token_map:
            raise ZerodhaNotConfiguredError("No active instruments with levels for today")
        level_errors = validate_active_level_sets(db, trading_day)
        if level_errors:
            raise ZerodhaNotConfiguredError("; ".join(level_errors))

        self.instrument_tokens = sorted(token_map.keys())
        self.last_error = None
        self.client = client_factory(token_map, session.access_token)
        self.client.start(self.instrument_tokens, self._handle_tick)
        self.running = True
        return self.status()

    def stop(self) -> Dict[str, object]:
        if self.client and getattr(self.client, "_ticker", None):
            close = getattr(self.client._ticker, "close", None)
            if close:
                close()
        self.running = False
        return self.status()

    def _handle_tick(self, tick: Tick) -> None:
        db = SessionLocal()
        try:
            process_tick(
                db=db,
                instrument_token=tick.instrument_token,
                last_price=tick.last_price,
                timestamp=tick.timestamp,
                volume=tick.volume,
            )
            self.processed_ticks += 1
        except Exception as exc:
            self.last_error = str(exc)
        finally:
            db.close()


zerodha_stream_service = ZerodhaStreamService()
