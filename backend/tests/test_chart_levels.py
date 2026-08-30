from app.schemas.technical import ChartLevels, TradeSetup
from app.services.chart_levels import sync_trade_setup_levels, validate_entry_zone


def test_sync_invalidation_level_from_stop_loss():
    setup = TradeSetup(
        bias="LONG",
        entry_zone=[3315, 3322],
        stop_loss=3290,
        take_profit=[3350, 3375],
        invalidation="Close below 3290",
        confidence=0.7,
    )
    levels = ChartLevels(trend="Bullish", support_levels=[3300], resistance_levels=[3350])
    setup, levels = sync_trade_setup_levels(setup, levels)
    assert setup.invalidation_level == 3290
    assert levels.invalidation_level == 3290


def test_validate_entry_zone_in_range():
    setup = TradeSetup(bias="LONG", entry_zone=[3315, 3322])
    levels = ChartLevels(support_levels=[3300], resistance_levels=[3360])
    assert validate_entry_zone(setup, levels) is True


def test_validate_entry_zone_out_of_range():
    setup = TradeSetup(bias="LONG", entry_zone=[3400, 3410])
    levels = ChartLevels(support_levels=[3300], resistance_levels=[3360])
    assert validate_entry_zone(setup, levels) is False
