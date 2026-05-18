import sys
import types
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.broker import zerodha_config
from backend.app.db.broker_sessions import save_zerodha_session
from backend.app.db.session import Base, get_db
from backend.app.main import app


def test_zerodha_instrument_sync_and_search(monkeypatch) -> None:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    class FakeKiteConnect:
        def __init__(self, api_key: str) -> None:
            self.api_key = api_key

        def set_access_token(self, access_token: str) -> None:
            self.access_token = access_token

        def instruments(self, exchange: str = None) -> list:
            return [
                {
                    "instrument_token": 111 if exchange == "NFO" else 333,
                    "tradingsymbol": "NIFTY26MAY22000CE"
                    if exchange == "NFO"
                    else "SENSEX26MAY74000CE",
                    "exchange": exchange or "NFO",
                    "instrument_type": "CE",
                    "lot_size": 50,
                    "tick_size": 0.05,
                },
                {
                    "instrument_token": 222 if exchange == "NFO" else 444,
                    "tradingsymbol": "BANKNIFTY26MAY48000PE"
                    if exchange == "NFO"
                    else "SENSEX2652175500PE",
                    "exchange": exchange or "NFO",
                    "instrument_type": "PE",
                    "lot_size": 15,
                    "tick_size": 0.05,
                },
                {
                    "instrument_token": 999,
                    "tradingsymbol": f"{exchange or 'NFO'}_FUT",
                    "exchange": exchange or "NFO",
                    "instrument_type": "FUT",
                    "lot_size": 1,
                    "tick_size": 0.05,
                },
            ]

    db = TestingSessionLocal()
    save_zerodha_session(
        db=db,
        access_token="access-token",
        public_token=None,
        user_id="AB1234",
        user_name="Test User",
        trading_day=date.today(),
    )
    db.close()

    def override_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setitem(sys.modules, "kiteconnect", types.SimpleNamespace(KiteConnect=FakeKiteConnect))
    monkeypatch.setattr(zerodha_config.zerodha_settings, "kite_api_key", "test-key")
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    sync_response = client.post("/instruments/sync/zerodha?exchange=NFO,BFO")
    bfo_sync_response = client.post("/instruments/sync/zerodha?exchange=BFO")
    search_response = client.get("/instruments?query=SENSEX&exchange=BFO")
    natural_search_response = client.get(
        "/instruments?query=SENSEX%2021%20MAY%2075500%20PUT&exchange=BFO"
    )
    app.dependency_overrides.clear()

    assert sync_response.status_code == 200
    assert sync_response.json()["synced"] == 4
    assert bfo_sync_response.status_code == 200
    assert bfo_sync_response.json()["synced"] == 2
    assert search_response.status_code == 200
    assert len(search_response.json()) == 2
    assert search_response.json()[0]["exchange"] == "BFO"
    assert search_response.json()[0]["lot_size"] == 1
    assert natural_search_response.status_code == 200
    assert natural_search_response.json()[0]["symbol"] == "SENSEX2652175500PE"
