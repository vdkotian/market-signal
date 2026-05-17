from datetime import date

from backend.app.core.enums import LevelSetStatus
from backend.app.db.repositories import assert_level_set_editable
from backend.app.models.tables import DailyLevelSet


def test_past_level_set_is_not_editable() -> None:
    level_set = DailyLevelSet(
        instrument_id=1,
        trading_day=date(2026, 5, 16),
        status=LevelSetStatus.ACTIVE.value,
    )

    try:
        assert_level_set_editable(level_set, today=date(2026, 5, 17))
    except ValueError as exc:
        assert "cannot be edited" in str(exc)
    else:
        raise AssertionError("Past level set should be locked from edits")

