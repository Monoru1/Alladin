"""
Tests K2 — Shadow Brain.

Vérifie :
- isolation structurelle (aucun import exécution/broker)
- déterminisme avec seed fixé
- production de propositions valides
- enregistrement d'outcomes et comparaisons
- persistance JSON et reprise
- calcul des métriques
- impossibilité d'envoyer un ordre réel
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alladin.research.snn.shadow_brain import (
    ShadowBrain,
    ShadowComparison,
    ShadowObservation,
    ShadowOutcome,
    ShadowProposal,
    ShadowSlowLoop,
    ShadowSNN,
    _action_return,
    _sharpe_proxy,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

T0 = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)

_BASE_OBS = ShadowObservation(
    symbol="BTCUSDT",
    cycle_id="C001",
    features=(0.5, 0.8, 0.2),
    feature_names=("rsi", "momentum", "vol"),
    min_vals=(0.0, -1.0, 0.0),
    max_vals=(1.0, 1.0, 1.0),
    observed_at=T0,
)

_BASE_OUTCOME = ShadowOutcome(
    cycle_id="C001",
    symbol="BTCUSDT",
    actual_return_pct=1.5,
    actual_action="LONG",
    pnl_r=0.5,
    recorded_at=T0,
)


def make_brain(tmp_path: Path | None = None) -> ShadowBrain:
    journal = tmp_path / "shadow_journal.json" if tmp_path else None
    return ShadowBrain(shadow_id="test_shadow", journal_path=journal, snn=ShadowSNN(seed=42))


# ---------------------------------------------------------------------------
# Isolation structurelle
# ---------------------------------------------------------------------------


class TestIsolation:
    def test_no_execution_imports(self) -> None:
        """Le module shadow_brain ne doit pas importer execution/, brokers/, orchestration/."""
        import alladin.research.snn.shadow_brain as mod

        source = inspect.getsource(mod)
        forbidden = [
            "from alladin.execution",
            "from alladin.brokers",
            "from alladin.orchestration",
            "import alladin.execution",
            "import alladin.brokers",
            "import alladin.orchestration",
        ]
        for pattern in forbidden:
            assert pattern not in source, f"Import interdit trouvé : {pattern}"

    def test_no_send_order_references(self) -> None:
        import alladin.research.snn.shadow_brain as mod

        source = inspect.getsource(mod)
        for pattern in ("send_order", "order_send", "place_order", "submit_order"):
            assert pattern not in source, f"Référence ordre trouvée : {pattern}"


# ---------------------------------------------------------------------------
# ShadowObservation — validation
# ---------------------------------------------------------------------------


class TestShadowObservation:
    def test_valid_observation(self) -> None:
        obs = _BASE_OBS
        assert obs.symbol == "BTCUSDT"
        assert len(obs.features) == 3

    def test_empty_features_raises(self) -> None:
        with pytest.raises(ValueError, match="non vide"):
            ShadowObservation(
                symbol="X",
                cycle_id="C",
                features=(),
                feature_names=(),
                min_vals=(),
                max_vals=(),
                observed_at=T0,
            )

    def test_mismatched_lengths_raises(self) -> None:
        with pytest.raises(ValueError):
            ShadowObservation(
                symbol="X",
                cycle_id="C",
                features=(0.5,),
                feature_names=("a", "b"),
                min_vals=(0.0,),
                max_vals=(1.0,),
                observed_at=T0,
            )

    def test_min_ge_max_raises(self) -> None:
        with pytest.raises(ValueError):
            ShadowObservation(
                symbol="X",
                cycle_id="C",
                features=(0.5,),
                feature_names=("a",),
                min_vals=(1.0,),
                max_vals=(0.0,),
                observed_at=T0,
            )


# ---------------------------------------------------------------------------
# ShadowSNN — déterminisme
# ---------------------------------------------------------------------------


class TestShadowSNN:
    def test_deterministic_with_same_seed(self) -> None:
        snn1 = ShadowSNN(seed=42)
        snn2 = ShadowSNN(seed=42)
        action1, conf1, sr1 = snn1.forward(_BASE_OBS)
        action2, conf2, sr2 = snn2.forward(_BASE_OBS)
        assert action1 == action2
        assert abs(conf1 - conf2) < 1e-9
        assert abs(sr1 - sr2) < 1e-9

    def test_different_seeds_may_differ(self) -> None:
        snn1 = ShadowSNN(seed=1)
        snn2 = ShadowSNN(seed=9999)
        results_1 = [snn1.forward(_BASE_OBS)[0] for _ in range(3)]
        results_2 = [snn2.forward(_BASE_OBS)[0] for _ in range(3)]
        # Ils peuvent diverger ; on vérifie surtout que les deux s'exécutent sans erreur
        assert all(a in ("LONG", "SHORT", "NO_TRADE") for a in results_1)
        assert all(a in ("LONG", "SHORT", "NO_TRADE") for a in results_2)

    def test_forward_returns_valid_action(self) -> None:
        snn = ShadowSNN(seed=42)
        action, confidence, spike_rate = snn.forward(_BASE_OBS)
        assert action in ("LONG", "SHORT", "NO_TRADE")
        assert 0.0 <= confidence <= 1.0
        assert spike_rate >= 0.0

    def test_learn_does_not_raise(self) -> None:
        snn = ShadowSNN(seed=42)
        snn.forward(_BASE_OBS)
        snn.learn(reward=1.0)
        snn.learn(reward=-1.0)

    def test_learn_affects_weights(self) -> None:
        snn1 = ShadowSNN(seed=42)
        snn2 = ShadowSNN(seed=42)
        snn1.forward(_BASE_OBS)
        snn1.learn(5.0)
        # Après apprentissage les poids doivent avoir changé
        w1 = [row[:] for row in snn1._rstdp_state.weights]
        w2 = [row[:] for row in snn2._rstdp_state.weights]
        assert w1 != w2


# ---------------------------------------------------------------------------
# ShadowBrain — cycle de base
# ---------------------------------------------------------------------------


class TestShadowBrainCore:
    def test_propose_returns_shadow_proposal(self) -> None:
        brain = make_brain()
        proposal = brain.observe_and_propose(_BASE_OBS)
        assert isinstance(proposal, ShadowProposal)
        assert proposal.cycle_id == "C001"
        assert proposal.symbol == "BTCUSDT"
        assert proposal.action in ("LONG", "SHORT", "NO_TRADE")

    def test_proposals_accumulated(self) -> None:
        brain = make_brain()
        brain.observe_and_propose(_BASE_OBS)
        obs2 = ShadowObservation(
            symbol="ETHUSDT", cycle_id="C002",
            features=(0.3, 0.6), feature_names=("a", "b"),
            min_vals=(0.0, 0.0), max_vals=(1.0, 1.0),
            observed_at=T0,
        )
        brain.observe_and_propose(obs2)
        assert len(brain.proposals()) == 2

    def test_register_outcome_without_proposal_returns_none(self) -> None:
        brain = make_brain()
        result = brain.register_outcome(_BASE_OUTCOME)
        assert result is None

    def test_register_outcome_with_proposal_returns_comparison(self) -> None:
        brain = make_brain()
        brain.observe_and_propose(_BASE_OBS)
        comparison = brain.register_outcome(_BASE_OUTCOME)
        assert isinstance(comparison, ShadowComparison)
        assert comparison.cycle_id == "C001"
        assert comparison.symbol == "BTCUSDT"

    def test_comparison_return_diff_computable(self) -> None:
        brain = make_brain()
        brain.observe_and_propose(_BASE_OBS)
        comparison = brain.register_outcome(_BASE_OUTCOME)
        assert comparison is not None
        assert comparison.return_diff_pct is not None

    def test_learning_triggered_on_outcome(self) -> None:
        snn = ShadowSNN(seed=42)
        brain2 = ShadowBrain(shadow_id="test", snn=snn)
        w_before = [row[:] for row in brain2.snn._rstdp_state.weights]
        brain2.observe_and_propose(_BASE_OBS)
        brain2.register_outcome(_BASE_OUTCOME)
        w_after = [row[:] for row in brain2.snn._rstdp_state.weights]
        assert w_before != w_after

    def test_slow_loop_is_the_explicit_learning_boundary(self) -> None:
        brain = make_brain()
        brain.observe_and_propose(_BASE_OBS)
        before = [row[:] for row in brain.snn._rstdp_state.weights]
        metrics = ShadowSlowLoop(brain).process([_BASE_OUTCOME])
        assert metrics.n_outcomes == 1
        assert brain.snn._rstdp_state.weights != before
        assert not ShadowSlowLoop(brain).candidate()


# ---------------------------------------------------------------------------
# Métriques
# ---------------------------------------------------------------------------


class TestShadowMetrics:
    def _brain_with_history(self) -> ShadowBrain:
        brain = make_brain()
        for i in range(15):
            obs = ShadowObservation(
                symbol="BTCUSDT", cycle_id=f"C{i:03d}",
                features=(0.5, 0.8), feature_names=("a", "b"),
                min_vals=(0.0, 0.0), max_vals=(1.0, 1.0),
                observed_at=T0,
            )
            brain.observe_and_propose(obs)
            outcome = ShadowOutcome(
                cycle_id=f"C{i:03d}", symbol="BTCUSDT",
                actual_return_pct=1.0 if i % 2 == 0 else -0.5,
                actual_action="LONG",
                recorded_at=T0,
            )
            brain.register_outcome(outcome)
        return brain

    def test_metrics_n_proposals(self) -> None:
        brain = self._brain_with_history()
        m = brain.compute_metrics()
        assert m.n_proposals == 15
        assert m.n_outcomes == 15
        assert m.n_comparable == 15

    def test_metrics_hit_rate_in_range(self) -> None:
        brain = self._brain_with_history()
        m = brain.compute_metrics()
        assert m.hit_rate is not None
        assert 0.0 <= m.hit_rate <= 1.0

    def test_metrics_avg_return_diff(self) -> None:
        brain = self._brain_with_history()
        m = brain.compute_metrics()
        assert m.avg_return_diff_pct is not None

    def test_empty_brain_metrics(self) -> None:
        brain = make_brain()
        m = brain.compute_metrics()
        assert m.n_proposals == 0
        assert m.hit_rate is None
        assert not m.is_candidate

    def test_metrics_to_dict(self) -> None:
        brain = self._brain_with_history()
        d = brain.compute_metrics().to_dict()
        assert "hit_rate" in d
        assert "is_candidate" in d


# ---------------------------------------------------------------------------
# Persistance JSON
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_journal_written_on_propose(self, tmp_path: Path) -> None:
        brain = make_brain(tmp_path)
        brain.observe_and_propose(_BASE_OBS)
        assert (tmp_path / "shadow_journal.json").exists()

    def test_journal_content_is_valid_json(self, tmp_path: Path) -> None:
        brain = make_brain(tmp_path)
        brain.observe_and_propose(_BASE_OBS)
        data = json.loads((tmp_path / "shadow_journal.json").read_text(encoding="utf-8"))
        assert "proposals" in data
        assert len(data["proposals"]) == 1

    def test_resume_from_journal(self, tmp_path: Path) -> None:
        brain1 = make_brain(tmp_path)
        brain1.observe_and_propose(_BASE_OBS)

        brain2 = ShadowBrain(
            shadow_id="test_shadow",
            journal_path=tmp_path / "shadow_journal.json",
        )
        assert len(brain2.proposals()) == 1
        assert brain2.proposals()[0].cycle_id == "C001"

    def test_journal_survives_corrupt_entry(self, tmp_path: Path) -> None:
        journal = tmp_path / "shadow_journal.json"
        journal.write_text('{"proposals": [{"bad": "data"}], "outcomes": []}', encoding="utf-8")
        brain = ShadowBrain(shadow_id="x", journal_path=journal)
        assert len(brain.proposals()) == 0  # entrée corrompue ignorée


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_action_return_long(self) -> None:
        assert _action_return("LONG", 2.0) == pytest.approx(2.0)

    def test_action_return_short(self) -> None:
        assert _action_return("SHORT", 2.0) == pytest.approx(-2.0)

    def test_action_return_no_trade(self) -> None:
        assert _action_return("NO_TRADE", 2.0) == pytest.approx(0.0)

    def test_sharpe_proxy_needs_two_points(self) -> None:
        assert _sharpe_proxy([]) is None
        assert _sharpe_proxy([1.0]) is None

    def test_sharpe_proxy_constant_series(self) -> None:
        assert _sharpe_proxy([1.0, 1.0, 1.0]) is None  # std == 0

    def test_sharpe_proxy_valid(self) -> None:
        result = _sharpe_proxy([1.0, 2.0, -1.0, 3.0])
        assert result is not None
        assert isinstance(result, float)
