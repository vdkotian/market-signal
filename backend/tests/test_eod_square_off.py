from datetime import date, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.enums import PositionStatus
from backend.app.db.session import Base, get_db
from backend.app.dto.trading_dto import Tick
from backend.app.main import app
from backend.app.market.tick_cache import tick_cache
from backend.app.models.tables import Instrument, Order, Position


def test_eod_square_off_closes_open_position_at_latest_price() -> None:
    tick_cache._latest_ticks.clear()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    instrument = Instrument(
        symbol="NIFTY_TEST_CE",
        exchange="NFO",
        instrument_token=1001,
        lot_size=50,
        tick_size=0.05,
    )
    db.add(instrument)
    db.flush()
    position = Position(
        instrument_id=instrument.id,
        trading_day=date.today(),
        quantity=1,
        entry_price=110,
        stoploss_price=100,
        trailing_stoploss_price=115,
        high_water_mark=120,
        status=PositionStatus.OPEN.value,
    )
    db.add(position)
    db.commit()
    tick_cache.update(
        Tick(
            instrument_token=1001,
            instrument_id=instrument.id,
            symbol="NIFTY_TEST_CE",
            last_price=118,
            timestamp=datetime.utcnow(),
        )
    )
    db.close()

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    response = client.post("/trading/eod-square-off")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["closed"][0]["exit_price"] == 118
    assert response.json()["closed"][0]["realized_pnl"] == 8

    verify = TestingSessionLocal()
    closed_position = verify.scalar(select(Position))
    order = verify.scalar(select(Order))
    verify.close()

    assert closed_position.status == PositionStatus.CLOSED.value
    assert closed_position.exit_price == 118
    assert order.side == "SELL"
    assert order.reason == "EOD square-off"


def test_eod_square_off_skips_when_latest_price_missing() -> None:
    tick_cache._latest_ticks.clear()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    instrument = Instrument(
        symbol="NIFTY_TEST_CE",
        exchange="NFO",
        instrument_token=1001,
        lot_size=50,
        tick_size=0.05,
    )
    db.add(instrument)
    db.flush()
    db.add(
        Position(
            instrument_id=instrument.id,
            trading_day=date.today(),
            quantity=1,
            entry_price=110,
            stoploss_price=100,
            trailing_stoploss_price=115,
            high_water_mark=120,
            status=PositionStatus.OPEN.value,
        )
    )
    db.commit()
    db.close()

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    response = client.post("/trading/eod-square-off")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["closed"] == []
    assert response.json()["skipped"][0]["reason"] == "No latest price available"
