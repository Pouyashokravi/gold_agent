"""Conflict + synthesis contract still usable by Manager answer path."""

from app.schemas.common import Horizon
from app.schemas.synthesis import Scenario, SynthesisOutput
from app.services.agent_conflict import analyze_agent_relations


def test_conflict_matrix_bullish_fundamental_bearish_technical():
    specialist_outputs = {
        "news": {"direction": "BULLISH", "confidence": 0.7, "horizon": "few_days", "drivers": ["dovish fed"]},
        "fundamental": {"direction": "BULLISH", "confidence": 0.75, "horizon": "medium_term", "drivers": ["real yields down"]},
        "technical": {"direction": "BEARISH", "confidence": 0.7, "horizon": "intraday", "drivers": ["support break"]},
    }
    analysis = analyze_agent_relations(specialist_outputs, "few_days")
    assert analysis.relations
    relations = {f"{r.agent_a}-{r.agent_b}": r.relation for r in analysis.relations}
    # Fundamental vs technical should surface a conflict of some kind
    ft = relations.get("fundamental-technical") or relations.get("technical-fundamental")
    assert ft is not None
    assert "CONFLICT" in ft or ft in {"PARTIAL_AGREEMENT", "HORIZON_CONFLICT", "DIRECTION_CONFLICT"}


def test_synthesis_output_contract_fields():
    s = SynthesisOutput(
        overall_direction="MIXED",
        confidence=0.55,
        horizon=Horizon.FEW_DAYS,
        base_case=Scenario(direction="MIXED", weight=0.5),
        bull_case=Scenario(direction="BULLISH", weight=0.25),
        bear_case=Scenario(direction="BEARISH", weight=0.25),
        key_drivers=["macro", "technical"],
        key_risks=["conflict"],
    )
    data = s.model_dump()
    for key in (
        "overall_direction",
        "confidence",
        "horizon",
        "key_drivers",
        "key_risks",
        "base_case",
        "bull_case",
        "bear_case",
    ):
        assert key in data
