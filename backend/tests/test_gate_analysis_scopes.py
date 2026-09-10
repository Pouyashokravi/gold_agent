"""Focused tests for semantic multi-select analysis_scopes and current-turn delta merge."""

from __future__ import annotations

import pytest

from app.schemas.common import Horizon, Intent
from app.schemas.conversation_gate import (
    AnalysisScope,
    ContextRelationship,
    ConversationGateOutput,
    NewlyResolvedFields,
    normalize_legacy_analysis_type,
    normalize_resolved_fields,
)
from app.schemas.manager import ComplexityLevel, GateRoute, ManagerPlan, ManagerTask
from app.services.conversation_gate import (
    GateValidationError,
    postprocess_gate_output,
    required_clarify_fields,
    validate_gate_output,
)
from app.services.policy import apply_manager_plan_constraints, validate_manager_plan


def test_normalize_legacy_general_to_comprehensive():
    assert normalize_legacy_analysis_type("GENERAL") == [
        AnalysisScope.FUNDAMENTAL,
        AnalysisScope.TECHNICAL,
        AnalysisScope.NEWS,
    ]
    assert normalize_legacy_analysis_type("FUNDAMENTAL") == [AnalysisScope.FUNDAMENTAL]
    rf = normalize_resolved_fields({"analysis_type": "GENERAL", "horizon": "medium_term"})
    assert rf["analysis_scopes"] == ["FUNDAMENTAL", "TECHNICAL", "NEWS"]
    assert "analysis_type" not in rf


def test_complete_outlook_no_clarify():
    """Case 1: 3-month gold outlook → STANDARD with comprehensive scopes."""
    llm = ConversationGateOutput(
        action=GateRoute.STANDARD,
        intent=Intent.MARKET_OUTLOOK,
        analysis_scopes=[
            AnalysisScope.FUNDAMENTAL,
            AnalysisScope.TECHNICAL,
            AnalysisScope.NEWS,
        ],
        horizon=Horizon.MEDIUM_TERM,
        context_relationship=ContextRelationship.INDEPENDENT,
        normalized_query="3-month gold outlook analysis",
        confidence=0.95,
        reason="complete outlook with medium-term horizon",
    )
    out = validate_gate_output(postprocess_gate_output(llm, None, "3-month gold outlook analysis", {}))
    assert out.action == GateRoute.STANDARD
    assert out.intent == Intent.MARKET_OUTLOOK
    assert out.horizon == Horizon.MEDIUM_TERM
    assert set(out.analysis_scopes) == {
        AnalysisScope.FUNDAMENTAL,
        AnalysisScope.TECHNICAL,
        AnalysisScope.NEWS,
    }
    assert out.missing_fields == []


def test_all_of_them_clarification_answer():
    """Case 2: analyse gold → all of them → scopes complete, horizon missing."""
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
        "previous_clarification_question": "What focus and time horizon should I use?",
    }
    llm = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        newly_resolved_fields=NewlyResolvedFields(
            intent=Intent.MARKET_OUTLOOK,
            analysis_scopes=[
                AnalysisScope.FUNDAMENTAL,
                AnalysisScope.TECHNICAL,
                AnalysisScope.NEWS,
            ],
        ),
        missing_fields=["horizon"],
        clarification_question="What time horizon should I use?",
        confidence=0.9,
        reason="user asked for all analysis types",
    )
    out = validate_gate_output(postprocess_gate_output(llm, pending, "all of them", {}))
    assert out.context_relationship == ContextRelationship.CLARIFICATION_ANSWER
    assert set(out.analysis_scopes) == {
        AnalysisScope.FUNDAMENTAL,
        AnalysisScope.TECHNICAL,
        AnalysisScope.NEWS,
    }
    assert out.missing_fields == ["horizon"]
    assert out.action == GateRoute.CLARIFY


def test_use_whatever_necessary_scopes():
    """Case 3: comprehensive scopes from natural language."""
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
        "previous_clarification_question": "What focus and time horizon?",
    }
    llm = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        newly_resolved_fields=NewlyResolvedFields(
            analysis_scopes=[
                AnalysisScope.FUNDAMENTAL,
                AnalysisScope.TECHNICAL,
                AnalysisScope.NEWS,
            ],
            intent=Intent.MARKET_OUTLOOK,
        ),
        confidence=0.9,
        reason="whatever analysis is necessary → comprehensive",
    )
    out = validate_gate_output(
        postprocess_gate_output(llm, pending, "use whatever analysis is necessary", {})
    )
    assert set(out.analysis_scopes) == {
        AnalysisScope.FUNDAMENTAL,
        AnalysisScope.TECHNICAL,
        AnalysisScope.NEWS,
    }
    assert out.missing_fields == ["horizon"]


def test_outlook_reply_resolves_comprehensive():
    """Case 4: outlook → market_outlook + comprehensive scopes."""
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
        "previous_clarification_question": "What focus and time horizon?",
    }
    llm = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        newly_resolved_fields=NewlyResolvedFields(
            intent=Intent.MARKET_OUTLOOK,
            analysis_scopes=[
                AnalysisScope.FUNDAMENTAL,
                AnalysisScope.TECHNICAL,
                AnalysisScope.NEWS,
            ],
        ),
        confidence=0.9,
        reason="outlook means comprehensive market outlook",
    )
    out = validate_gate_output(postprocess_gate_output(llm, pending, "outlook", {}))
    assert out.intent == Intent.MARKET_OUTLOOK
    assert set(out.analysis_scopes) == {
        AnalysisScope.FUNDAMENTAL,
        AnalysisScope.TECHNICAL,
        AnalysisScope.NEWS,
    }
    assert out.missing_fields == ["horizon"]


def test_descriptive_fundamental_reply():
    """Case 5: rates/inflation descriptive → FUNDAMENTAL only."""
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
        "previous_clarification_question": "What focus and time horizon?",
    }
    llm = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        newly_resolved_fields=NewlyResolvedFields(
            intent=Intent.FUNDAMENTAL_ANALYSIS,
            analysis_scopes=[AnalysisScope.FUNDAMENTAL],
        ),
        confidence=0.9,
        reason="macro rates inflation Fed",
    )
    out = validate_gate_output(
        postprocess_gate_output(
            llm, pending, "focus on rates, inflation, and Fed policy", {}
        )
    )
    assert out.analysis_scopes == [AnalysisScope.FUNDAMENTAL]
    assert out.missing_fields == ["horizon"]


def test_combined_macro_and_momentum_complete():
    """Case 6: FUNDAMENTAL+TECHNICAL with short-term horizon, no clarify."""
    llm = ConversationGateOutput(
        action=GateRoute.STANDARD,
        intent=Intent.MARKET_OUTLOOK,
        analysis_scopes=[AnalysisScope.FUNDAMENTAL, AnalysisScope.TECHNICAL],
        horizon=Horizon.SHORT_TERM,
        context_relationship=ContextRelationship.INDEPENDENT,
        normalized_query="Combine macro picture with price momentum for next month",
        confidence=0.92,
        reason="macro + momentum, one-month horizon",
    )
    out = validate_gate_output(
        postprocess_gate_output(
            llm,
            None,
            "Combine the macro picture with price momentum for the next month",
            {},
        )
    )
    assert out.action == GateRoute.STANDARD
    assert set(out.analysis_scopes) == {AnalysisScope.FUNDAMENTAL, AnalysisScope.TECHNICAL}
    assert out.horizon == Horizon.SHORT_TERM
    assert out.missing_fields == []


def test_current_reply_overrides_stale_general():
    """Case 7: pending GENERAL/comprehensive + fundamental delta → FUNDAMENTAL only."""
    pending = {
        "original_query": "3-month gold outlook analysis",
        "resolved_fields": {"analysis_type": "GENERAL", "horizon": "medium_term"},
        "missing_fields": ["analysis_scopes"],
        "previous_clarification_question": "What focus should I use?",
    }
    llm = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        intent=Intent.MARKET_OUTLOOK,
        analysis_scopes=[
            AnalysisScope.FUNDAMENTAL,
            AnalysisScope.TECHNICAL,
            AnalysisScope.NEWS,
        ],
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        newly_resolved_fields=NewlyResolvedFields(
            intent=Intent.FUNDAMENTAL_ANALYSIS,
            analysis_scopes=[AnalysisScope.FUNDAMENTAL],
        ),
        confidence=0.95,
        reason="user said fundamental",
    )
    out = validate_gate_output(postprocess_gate_output(llm, pending, "fundamental", {}))
    assert out.analysis_scopes == [AnalysisScope.FUNDAMENTAL]
    assert out.intent == Intent.FUNDAMENTAL_ANALYSIS
    assert out.horizon == Horizon.MEDIUM_TERM
    assert out.delta_conflict is True
    assert out.action == GateRoute.STANDARD
    assert out.missing_fields == []


def test_no_progress_clarification_raises_for_repair():
    """Case 8: empty delta + zero conf + blank reason + same question → invalid."""
    pending = {
        "original_query": "analyse gold",
        "resolved_fields": {},
        "missing_fields": ["analysis_scopes", "horizon"],
        "previous_clarification_question": "What focus and time horizon should I use?",
    }
    llm = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        newly_resolved_fields=NewlyResolvedFields(),
        missing_fields=["analysis_scopes", "horizon"],
        clarification_question="What focus and time horizon should I use?",
        confidence=0.0,
        reason="",
    )
    with pytest.raises(GateValidationError, match="no-progress"):
        postprocess_gate_output(llm, pending, "all of them", {})


def test_no_progress_independent_relationship_still_invalid():
    """Wrongly labeled INDEPENDENT with empty delta must still raise for repair."""
    pending = {
        "original_query": "technical analyse gold",
        "resolved_fields": {"analysis_scopes": ["TECHNICAL"]},
        "missing_fields": ["horizon"],
        "previous_clarification_question": "What time horizon should I use?",
    }
    llm = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.INDEPENDENT,
        analysis_scopes=[AnalysisScope.TECHNICAL],
        newly_resolved_fields=NewlyResolvedFields(),
        missing_fields=["horizon"],
        clarification_question="What time horizon should I use?",
        confidence=0.0,
        reason="",
    )
    with pytest.raises(GateValidationError, match="no-progress"):
        postprocess_gate_output(llm, pending, "today", {})


def test_clarification_preserves_technical_scope_when_horizon_resolved():
    """Pending TECHNICAL + horizon delta must not become comprehensive outlook."""
    pending = {
        "original_query": "technical analyse gold",
        "resolved_fields": {
            "analysis_scopes": ["TECHNICAL"],
            "intent": "technical_analysis",
        },
        "missing_fields": ["horizon"],
        "previous_clarification_question": "What time horizon should I use?",
    }
    # Model wrongly invents comprehensive top-level scopes; delta only has horizon
    llm = ConversationGateOutput(
        action=GateRoute.CLARIFY,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        intent=Intent.MARKET_OUTLOOK,
        analysis_scopes=[
            AnalysisScope.FUNDAMENTAL,
            AnalysisScope.TECHNICAL,
            AnalysisScope.NEWS,
        ],
        newly_resolved_fields=NewlyResolvedFields(horizon=Horizon.INTRADAY),
        confidence=0.9,
        reason="today → intraday",
    )
    out = validate_gate_output(postprocess_gate_output(llm, pending, "today", {}))
    assert out.action == GateRoute.STANDARD
    assert out.analysis_scopes == [AnalysisScope.TECHNICAL]
    assert out.horizon == Horizon.INTRADAY
    assert out.intent == Intent.TECHNICAL_ANALYSIS
    assert out.missing_fields == []


def test_short_term_preserves_technical_scope():
    pending = {
        "original_query": "technical analyse gold",
        "resolved_fields": {"analysis_scopes": ["TECHNICAL"]},
        "missing_fields": ["horizon"],
        "previous_clarification_question": "What time horizon should I use?",
    }
    llm = ConversationGateOutput(
        action=GateRoute.STANDARD,
        context_relationship=ContextRelationship.CLARIFICATION_ANSWER,
        intent=Intent.MARKET_OUTLOOK,
        analysis_scopes=[
            AnalysisScope.FUNDAMENTAL,
            AnalysisScope.TECHNICAL,
            AnalysisScope.NEWS,
        ],
        newly_resolved_fields=NewlyResolvedFields(horizon=Horizon.SHORT_TERM),
        normalized_query="technical analyse gold",
        confidence=0.95,
        reason="short term",
    )
    out = validate_gate_output(postprocess_gate_output(llm, pending, "short term", {}))
    assert out.action == GateRoute.STANDARD
    assert out.analysis_scopes == [AnalysisScope.TECHNICAL]
    assert out.horizon == Horizon.SHORT_TERM
    assert out.intent == Intent.TECHNICAL_ANALYSIS


def test_manager_ensures_required_scopes():
    """Case 9: policy ensures specialists for each scope."""
    plan = ManagerPlan(
        goal="outlook",
        horizon=Horizon.MEDIUM_TERM,
        complexity=ComplexityLevel.STANDARD,
        tasks=[ManagerTask(id="q1", kind="tool_quote", task="quote")],
        rationale="thin plan",
    )
    scopes = [AnalysisScope.FUNDAMENTAL, AnalysisScope.TECHNICAL, AnalysisScope.NEWS]
    out = apply_manager_plan_constraints(plan, "3-month outlook", False, analysis_scopes=scopes)
    kinds = {t.kind for t in out.tasks}
    assert "agent_fundamental" in kinds
    assert "agent_technical" in kinds
    assert "agent_news" in kinds
    warnings = validate_manager_plan(out, analysis_scopes=scopes)
    assert not any("Missing required specialist" in w for w in warnings)

    single = apply_manager_plan_constraints(
        plan, "fundamental only", False, analysis_scopes=[AnalysisScope.FUNDAMENTAL]
    )
    kinds2 = {t.kind for t in single.tasks}
    assert "agent_fundamental" in kinds2
    assert "agent_technical" not in kinds2


def test_news_analysis_may_omit_horizon_when_timing_clear():
    missing = required_clarify_fields(
        Intent.NEWS_ANALYSIS,
        scopes=[AnalysisScope.NEWS],
        horizon=None,
        timing_explicit=True,
    )
    assert missing == []


def test_default_plan_from_gate_uses_scopes():
    from app.services.manager_runtime import _default_plan_from_gate

    decision = ConversationGateOutput(
        action=GateRoute.STANDARD,
        intent=Intent.FUNDAMENTAL_ANALYSIS,
        analysis_scopes=[AnalysisScope.FUNDAMENTAL],
        horizon=Horizon.SHORT_TERM,
        complexity=ComplexityLevel.STANDARD,
        normalized_query="fundamental short term",
        confidence=0.9,
        reason="ok",
    )
    plan = _default_plan_from_gate("fundamental short term", decision, False)
    kinds = {t.kind for t in plan.tasks}
    assert "agent_fundamental" in kinds
    assert "agent_news" not in kinds
