from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.enums import LevelSetStatus, PositionStatus
from backend.app.db.session import Base, get_db
from backend.app.main import app
from backend.app.market.tick_cache import tick_cache
from backend.app.models.tables import DailyLevelSet, Instrument, Level, Order, Position


def test_mock_tick_endpoint_persists_paper_position_and_trailing_stop() -> None:
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
    level_set = DailyLevelSet(
        instrument_id=instrument.id,
        trading_day=date.today(),
        status=LevelSetStatus.ACTIVE.value,
        created_by="test",
        updated_by="test",
    )
    level_set.levels.extend(
        [
            Level(level_name="L0", price=100, sort_order=0, role="STOPLOSS"),
            Level(level_name="L1", price=110, sort_order=1, role="ENTRY"),
            Level(level_name="L2", price=120, sort_order=2, role="CHECKPOINT"),
        ]
    )
    db.add(level_set)
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

    first = client.post("/ticks/mock", json={"instrument_token": 1001, "last_price": 108})
    entry = client.post("/ticks/mock", json={"instrument_token": 1001, "last_price": 110})
    checkpoint = client.post("/ticks/mock", json={"instrument_token": 1001, "last_price": 120})

    app.dependency_overrides.clear()

    assert first.status_code == 200
    assert entry.status_code == 200
    assert checkpoint.status_code == 200
    assert entry.json()["results"][0]["success"] is True
    assert checkpoint.json()["position"]["trailing_stoploss_price"] == 115

    verify_db = TestingSessionLocal()
    position = verify_db.scalar(select(Position))
    orders = verify_db.scalars(select(Order)).all()
    verify_db.close()

    assert position is not None
    assert position.status == PositionStatus.OPEN.value
    assert position.entry_price == 110
    assert position.trailing_stoploss_price == 115
    assert len(orders) == 1
    assert orders[0].side == "BUY"
