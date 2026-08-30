import pytest

from app.schemas.common import Horizon
from app.services.agent_conflict import ConflictType, analyze_agent_relations, compute_confidence_adjustment
from app.schemas.synthesis import AgentPairRelation


def _outputs(news=None, fund=None, tech=None):
    base = {}
    if news is not None:
        base["news"] = news
    if fund is not None:
        base["fundamental"] = fund
    if tech is not None:
        base["technical"] = tech
    return base


def test_agreement_when_same_direction():
    outputs = _outputs(
        news={"direction": "BULLISH", "confidence": 0.8, "horizon": "few_days", "drivers": ["Gold rally"]},
        fund={"direction": "BULLISH", "confidence": 0.75, "horizon": "medium_term", "drivers": ["Dovish Fed"]},
        tech={"direction": "BULLISH", "confidence": 0.7, "horizon": "intraday", "drivers": ["Breakout"]},
    )
    analysis = analyze_agent_relations(outputs, Horizon.FEW_DAYS)
    agreements = [r for r in analysis.relations if r.relation == ConflictType.AGREEMENT.value]
    assert len(agreements) >= 1
    assert analysis.confidence_adjustment >= 0


def test_direction_conflict_same_horizon():
    outputs = _outputs(
        fund={"direction": "BULLISH", "confidence": 0.8, "horizon": "intraday", "drivers": ["Macro bid"]},
        tech={"direction": "BEARISH", "confidence": 0.75, "horizon": "intraday", "drivers": ["Bearish structure"]},
    )
    analysis = analyze_agent_relations(outputs, Horizon.INTRADAY)
    rel = next(r for r in analysis.relations if r.agent_a == "fundamental" and r.agent_b == "technical")
    assert rel.relation == ConflictType.DIRECTION_CONFLICT.value
    assert analysis.confidence_adjustment < 0


def test_horizon_conflict_not_full_penalty():
    outputs = _outputs(
        fund={"direction": "BULLISH", "confidence": 0.8, "horizon": "medium_term", "drivers": ["Macro bid"]},
        tech={"direction": "BEARISH", "confidence": 0.75, "horizon": "intraday", "drivers": ["Short-term selloff"]},
    )
    analysis = analyze_agent_relations(outputs, Horizon.MEDIUM_TERM)
    rel = next(r for r in analysis.relations if "fundamental" in (r.agent_a, r.agent_b) and "technical" in (r.agent_a, r.agent_b))
    assert rel.relation == ConflictType.HORIZON_CONFLICT.value

    dir_conflict_adj = compute_confidence_adjustment([
        AgentPairRelation(agent_a="fundamental", agent_b="technical", relation=ConflictType.DIRECTION_CONFLICT.value, severity=0.8, explanation=""),
    ])
    horizon_adj = compute_confidence_adjustment([
        AgentPairRelation(agent_a="fundamental", agent_b="technical", relation=ConflictType.HORIZON_CONFLICT.value, severity=0.8, explanation=""),
    ])
    assert dir_conflict_adj < horizon_adj


def test_partial_agreement_with_neutral():
    outputs = _outputs(
        news={"direction": "NEUTRAL", "confidence": 0.5, "horizon": "few_days", "drivers": []},
        tech={"direction": "BULLISH", "confidence": 0.7, "horizon": "intraday", "drivers": []},
    )
    analysis = analyze_agent_relations(outputs, Horizon.FEW_DAYS)
    rel = next(r for r in analysis.relations if r.agent_a == "news" and r.agent_b == "technical")
    assert rel.relation == ConflictType.PARTIAL_AGREEMENT.value
