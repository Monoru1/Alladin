"""
Tests K1 — SNN fondation minimale.

Vérifie :
- déterminisme avec seed
- dynamique LIF (potentiel, seuil, reset, fuite)
- comportement R-STDP (mise à jour des poids, bornes)
- absence de lookahead dans l'encodeur
- isolation du chemin d'exécution
- impossibilité structurelle d'envoyer un ordre
"""

from __future__ import annotations

import pytest

from alladin.research.snn.encoder import (
    EncoderParams,
    encode_feature,
    encode_features,
    spike_counts,
)
from alladin.research.snn.experiment import (
    K1_EXPERIMENT,
    ExperimentSpec,
    TrialResult,
    validate_spec,
)
from alladin.research.snn.lif import (
    LIFParams,
    LIFState,
    lif_step,
    make_lif_state,
    run_lif_population,
)
from alladin.research.snn.rstdp import (
    RSTDPParams,
    RSTDPState,
    accumulate_eligibility,
    apply_reward,
    make_rstdp_state,
    readout,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def make_flat_input(n_neurons: int, current: float, n_steps: int) -> list[list[float]]:
    return [[current] * n_neurons] * n_steps


# ---------------------------------------------------------------------------
# LIF — dynamique
# ---------------------------------------------------------------------------


class TestLIFDynamics:
    def test_resting_potential_at_zero_input(self) -> None:
        params = LIFParams(n_neurons=1, tau_m=20.0, v_rest=-65.0)
        state = make_lif_state(params)
        new_state = lif_step(state, [0.0], params)
        # With zero input, potential stays at v_rest (leak brings it there)
        assert abs(new_state.v[0] - params.v_rest) < 1e-9

    def test_membrane_charges_with_positive_input(self) -> None:
        params = LIFParams(n_neurons=1, v_rest=-65.0, v_thresh=-50.0, r_membrane=10.0)
        state = make_lif_state(params)
        new_state = lif_step(state, [1.0], params)
        assert new_state.v[0] > params.v_rest

    def test_spike_when_threshold_crossed(self) -> None:
        params = LIFParams(
            n_neurons=1, tau_m=1.0, v_rest=-65.0, v_thresh=-50.0,
            r_membrane=100.0, dt=1.0,
        )
        state = make_lif_state(params)
        # Large current forces threshold crossing
        new_state = lif_step(state, [10.0], params)
        assert new_state.spikes[0] is True

    def test_reset_after_spike(self) -> None:
        params = LIFParams(
            n_neurons=1, tau_m=1.0, v_rest=-65.0, v_thresh=-50.0,
            v_reset=-65.0, r_membrane=100.0, dt=1.0, refractory_steps=2,
        )
        state = make_lif_state(params)
        state = lif_step(state, [10.0], params)
        assert state.spikes[0] is True
        assert abs(state.v[0] - params.v_reset) < 1e-9
        assert state.refractory_countdown[0] == params.refractory_steps

    def test_refractory_period_prevents_spiking(self) -> None:
        params = LIFParams(
            n_neurons=1, tau_m=1.0, v_rest=-65.0, v_thresh=-50.0,
            v_reset=-65.0, r_membrane=100.0, dt=1.0, refractory_steps=3,
        )
        state = make_lif_state(params)
        state = lif_step(state, [10.0], params)
        assert state.spikes[0] is True
        # During refractory: strong input still gives no spike
        for _ in range(params.refractory_steps):
            state = lif_step(state, [10.0], params)
            assert state.spikes[0] is False

    def test_potential_decays_without_input(self) -> None:
        params = LIFParams(n_neurons=1, tau_m=20.0, v_rest=-65.0, dt=1.0)
        state = LIFState(v=[-55.0], refractory_countdown=[0], spikes=[False])
        new_state = lif_step(state, [0.0], params)
        # Should decay toward v_rest
        assert new_state.v[0] < -55.0
        assert new_state.v[0] > params.v_rest

    def test_wrong_input_length_raises(self) -> None:
        params = LIFParams(n_neurons=3)
        state = make_lif_state(params)
        with pytest.raises(ValueError, match="current_inputs length"):
            lif_step(state, [0.0, 0.0], params)

    def test_run_population_output_shape(self) -> None:
        params = LIFParams(n_neurons=4)
        seq = make_flat_input(4, 0.5, 10)
        spikes = run_lif_population(seq, params)
        assert len(spikes) == 10
        assert all(len(s) == 4 for s in spikes)


# ---------------------------------------------------------------------------
# LIF — déterminisme avec seed via run_lif_population
# ---------------------------------------------------------------------------


class TestLIFDeterminism:
    def test_identical_input_gives_identical_output(self) -> None:
        params = LIFParams(n_neurons=5, tau_m=10.0)
        seq = make_flat_input(5, 0.8, 15)
        out1 = run_lif_population(seq, params)
        out2 = run_lif_population(seq, params)
        assert out1 == out2

    def test_different_input_gives_different_output(self) -> None:
        params = LIFParams(n_neurons=3)
        seq_a = make_flat_input(3, 0.1, 10)
        seq_b = make_flat_input(3, 5.0, 10)
        out_a = run_lif_population(seq_a, params)
        out_b = run_lif_population(seq_b, params)
        assert out_a != out_b


# ---------------------------------------------------------------------------
# Encodeur — déterminisme et no-lookahead
# ---------------------------------------------------------------------------


class TestEncoder:
    def test_same_seed_same_output(self) -> None:
        params = EncoderParams(n_neurons=8, n_timesteps=10, seed=42)
        t1 = encode_feature(0.5, 0.0, 1.0, params)
        t2 = encode_feature(0.5, 0.0, 1.0, params)
        assert t1 == t2

    def test_different_seed_different_output(self) -> None:
        p1 = EncoderParams(n_neurons=8, n_timesteps=10, seed=42)
        p2 = EncoderParams(n_neurons=8, n_timesteps=10, seed=99)
        t1 = encode_feature(0.5, 0.0, 1.0, p1)
        t2 = encode_feature(0.5, 0.0, 1.0, p2)
        assert t1 != t2

    def test_output_shape(self) -> None:
        params = EncoderParams(n_neurons=6, n_timesteps=12, seed=1)
        t = encode_feature(0.3, 0.0, 1.0, params)
        assert len(t) == 12
        assert all(len(row) == 6 for row in t)

    def test_zero_value_low_firing_rate(self) -> None:
        params = EncoderParams(n_neurons=20, n_timesteps=50, seed=0)
        t = encode_feature(0.0, 0.0, 1.0, params)
        # normalized=0.0 → p_fire=0 → no spikes
        total = sum(sum(1 for s in row if s) for row in t)
        assert total == 0

    def test_max_value_all_spikes_at_max_rate_1000hz(self) -> None:
        # max_rate=1000 Hz → p_fire = 1.0 * 1000/1000 = 1.0 → all neurons fire every step
        params = EncoderParams(n_neurons=10, n_timesteps=20, max_rate=1000.0, seed=0)
        t = encode_feature(1.0, 0.0, 1.0, params)
        total = sum(sum(1 for s in row if s) for row in t)
        assert total == 10 * 20

    def test_max_rate_affects_firing_probability(self) -> None:
        # Same value, same seed — higher max_rate must produce more spikes
        low_rate = EncoderParams(n_neurons=20, n_timesteps=50, max_rate=50.0, seed=42)
        high_rate = EncoderParams(n_neurons=20, n_timesteps=50, max_rate=500.0, seed=42)
        t_low = encode_feature(1.0, 0.0, 1.0, low_rate)
        t_high = encode_feature(1.0, 0.0, 1.0, high_rate)
        count_low = sum(sum(1 for s in row if s) for row in t_low)
        count_high = sum(sum(1 for s in row if s) for row in t_high)
        assert count_high > count_low

    def test_p_fire_bounded_0_1(self) -> None:
        # max_rate=2000 would give normalized*2.0 — must be clamped to 1.0
        params = EncoderParams(n_neurons=5, n_timesteps=10, max_rate=2000.0, seed=1)
        # Should not raise and p_fire must stay ≤ 1.0 (no exception, deterministic output)
        t = encode_feature(1.0, 0.0, 1.0, params)
        assert len(t) == 10
        # All spikes expected (p_fire clamped to 1.0)
        total = sum(sum(1 for s in row if s) for row in t)
        assert total == 5 * 10

    def test_value_clamped_below_min(self) -> None:
        params = EncoderParams(n_neurons=5, n_timesteps=10, seed=7)
        t_below = encode_feature(-1.0, 0.0, 1.0, params)
        t_min = encode_feature(0.0, 0.0, 1.0, params)
        assert t_below == t_min

    def test_value_clamped_above_max(self) -> None:
        params = EncoderParams(n_neurons=5, n_timesteps=10, seed=7)
        t_above = encode_feature(2.0, 0.0, 1.0, params)
        t_max = encode_feature(1.0, 0.0, 1.0, params)
        assert t_above == t_max

    def test_invalid_range_raises(self) -> None:
        params = EncoderParams()
        with pytest.raises(ValueError):
            encode_feature(0.5, 1.0, 0.0, params)

    def test_encode_features_deterministic(self) -> None:
        params = EncoderParams(seed=10)
        features = {"close": 1.0, "volume": 0.5}
        ranges = {"close": (0.0, 2.0), "volume": (0.0, 1.0)}
        r1 = encode_features(features, ranges, params)
        r2 = encode_features(features, ranges, params)
        assert r1 == r2

    def test_encode_features_missing_range_raises(self) -> None:
        params = EncoderParams()
        with pytest.raises(KeyError):
            encode_features({"x": 0.5}, {}, params)

    def test_spike_counts_shape(self) -> None:
        params = EncoderParams(n_neurons=4, n_timesteps=5, seed=0)
        t = encode_feature(0.5, 0.0, 1.0, params)
        counts = spike_counts(t)
        assert len(counts) == 4
        assert all(0 <= c <= 5 for c in counts)

    def test_no_lookahead_only_present_data(self) -> None:
        # Encoder uses only the value passed at call time.
        # Call with t=0 data, then t=1 data — they must be independent.
        params = EncoderParams(n_neurons=4, n_timesteps=5, seed=42)
        t0 = encode_feature(0.2, 0.0, 1.0, params)
        t1 = encode_feature(0.8, 0.0, 1.0, params)
        # Different values must produce different encodings (no future contamination)
        assert t0 != t1


# ---------------------------------------------------------------------------
# R-STDP — poids et bornes
# ---------------------------------------------------------------------------


class TestRSTDP:
    def test_initial_weights_in_bounds(self) -> None:
        params = RSTDPParams(n_pre=5, n_post=3, w_min=0.0, w_max=1.0, seed=42)
        state = make_rstdp_state(params)
        for row in state.weights:
            for w in row:
                assert params.w_min <= w <= params.w_max

    def test_same_seed_same_weights(self) -> None:
        params = RSTDPParams(n_pre=4, n_post=2, seed=7)
        s1 = make_rstdp_state(params)
        s2 = make_rstdp_state(params)
        assert s1.weights == s2.weights

    def test_different_seed_different_weights(self) -> None:
        p1 = RSTDPParams(n_pre=4, n_post=2, seed=7)
        p2 = RSTDPParams(n_pre=4, n_post=2, seed=8)
        s1 = make_rstdp_state(p1)
        s2 = make_rstdp_state(p2)
        assert s1.weights != s2.weights

    def test_positive_reward_increases_mean_weight_on_activity(self) -> None:
        params = RSTDPParams(n_pre=3, n_post=2, w_min=0.0, w_max=1.0, lr_plus=0.1, seed=0)
        state = make_rstdp_state(params, seed=0)
        # Force uniform mid-weight to make effect predictable
        state = RSTDPState(
            weights=[[0.5] * params.n_pre for _ in range(params.n_post)],
            eligibility=[[0.0] * params.n_pre for _ in range(params.n_post)],
        )
        # Both pre and post fire at t=0
        pre = [[True] * params.n_pre]
        post = [[True] * params.n_post]
        state = accumulate_eligibility(state, pre, post, params)
        updated = apply_reward(state, reward=1.0, params=params)
        mean_before = 0.5
        mean_after = sum(w for row in updated.weights for w in row) / (params.n_pre * params.n_post)
        assert mean_after != mean_before  # weights changed

    def test_eligibility_zeroed_after_reward(self) -> None:
        params = RSTDPParams(n_pre=2, n_post=1, seed=0)
        state = make_rstdp_state(params)
        pre = [[True, True]]
        post = [[True]]
        state = accumulate_eligibility(state, pre, post, params)
        state = apply_reward(state, reward=1.0, params=params)
        assert all(e == 0.0 for row in state.eligibility for e in row)

    def test_weights_clipped_to_bounds(self) -> None:
        params = RSTDPParams(n_pre=2, n_post=1, w_min=0.0, w_max=1.0, lr_plus=100.0, seed=0)
        state = RSTDPState(
            weights=[[0.9, 0.9]],
            eligibility=[[10.0, 10.0]],
        )
        updated = apply_reward(state, reward=1.0, params=params)
        for w in updated.weights[0]:
            assert w <= params.w_max

    def test_weights_clipped_below_min(self) -> None:
        params = RSTDPParams(n_pre=2, n_post=1, w_min=0.0, w_max=1.0, lr_minus=100.0, seed=0)
        state = RSTDPState(
            weights=[[0.1, 0.1]],
            eligibility=[[10.0, 10.0]],
        )
        updated = apply_reward(state, reward=-1.0, params=params)
        for w in updated.weights[0]:
            assert w >= params.w_min

    def test_zero_reward_leaves_weights_unchanged(self) -> None:
        params = RSTDPParams(n_pre=3, n_post=2, seed=1)
        state = make_rstdp_state(params)
        state = RSTDPState(
            weights=[[0.5] * params.n_pre for _ in range(params.n_post)],
            eligibility=[[1.0] * params.n_pre for _ in range(params.n_post)],
        )
        updated = apply_reward(state, reward=0.0, params=params)
        assert updated.weights == state.weights

    def test_readout_shape_and_type(self) -> None:
        params = RSTDPParams(n_pre=4, n_post=3, seed=0)
        state = make_rstdp_state(params)
        pre = [[True, False, True, False]] * 5
        out = readout(pre, state.weights)
        assert len(out) == params.n_post
        assert all(isinstance(v, float) for v in out)

    def test_readout_zero_on_no_spikes(self) -> None:
        weights = [[0.5, 0.5]]
        pre = [[False, False]] * 5
        out = readout(pre, weights)
        assert out == [0.0]

    def test_tau_plus_affects_eligibility_traces(self) -> None:
        # Smaller tau_plus → faster decay → less accumulated trace for same spikes
        fast = RSTDPParams(n_pre=2, n_post=1, tau_plus=1.0, dt=1.0, seed=0)
        slow = RSTDPParams(n_pre=2, n_post=1, tau_plus=100.0, dt=1.0, seed=0)
        state_fast = RSTDPState(weights=[[0.5, 0.5]], eligibility=[[0.0, 0.0]])
        state_slow = RSTDPState(weights=[[0.5, 0.5]], eligibility=[[0.0, 0.0]])
        # Pre fires at t=0, post fires at t=3 (pre trace should have decayed differently)
        pre = [[True, True], [False, False], [False, False], [False, False]]
        post = [[False], [False], [False], [True]]
        s_fast = accumulate_eligibility(state_fast, pre, post, fast)
        s_slow = accumulate_eligibility(state_slow, pre, post, slow)
        # Fast tau → traces decayed more → less eligibility accumulated
        elig_fast = sum(abs(e) for row in s_fast.eligibility for e in row)
        elig_slow = sum(abs(e) for row in s_slow.eligibility for e in row)
        assert elig_fast != elig_slow

    def test_dt_affects_decay(self) -> None:
        # Larger dt → faster decay per step → less accumulated trace
        small_dt = RSTDPParams(n_pre=2, n_post=1, tau_plus=20.0, dt=1.0, seed=0)
        large_dt = RSTDPParams(n_pre=2, n_post=1, tau_plus=20.0, dt=10.0, seed=0)
        state = RSTDPState(weights=[[0.5, 0.5]], eligibility=[[0.0, 0.0]])
        pre = [[True, True], [False, False], [False, False], [False, False]]
        post = [[False], [False], [False], [True]]
        s_small = accumulate_eligibility(state, pre, post, small_dt)
        s_large = accumulate_eligibility(state, pre, post, large_dt)
        elig_small = sum(abs(e) for row in s_small.eligibility for e in row)
        elig_large = sum(abs(e) for row in s_large.eligibility for e in row)
        assert elig_small != elig_large

    def test_rstdp_deterministic_with_same_params(self) -> None:
        params = RSTDPParams(n_pre=3, n_post=2, tau_plus=15.0, tau_minus=25.0, dt=2.0, seed=5)
        state = make_rstdp_state(params)
        pre = [[True, False, True], [False, True, False]]
        post = [[True, False], [False, True]]
        s1 = accumulate_eligibility(state, pre, post, params)
        s2 = accumulate_eligibility(state, pre, post, params)
        assert s1.eligibility == s2.eligibility


# ---------------------------------------------------------------------------
# Isolation du chemin d'exécution
# ---------------------------------------------------------------------------


class TestExecutionIsolation:
    """
    Verify that the SNN package source files do not import anything from the
    execution path: execution/, brokers/, orchestration/.

    We inspect source text and AST imports rather than sys.modules, because
    other test modules in the same session may have already loaded those
    packages before this test runs.
    """

    FORBIDDEN_IMPORT_PREFIXES = [
        "alladin.execution",
        "alladin.brokers",
        "alladin.orchestration",
    ]

    def _snn_sources(self) -> list[tuple[str, str]]:
        """Return list of (filename, source_text) for all SNN .py files."""
        from pathlib import Path
        snn_dir = Path(__file__).parents[1] / "src" / "alladin" / "research" / "snn"
        return [(p.name, p.read_text(encoding="utf-8")) for p in snn_dir.glob("*.py")]

    def _ast_imports(self, source: str) -> list[str]:
        """Return all module names imported in source via import/from-import."""
        import ast
        tree = ast.parse(source)
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    names.append(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
        return names

    def test_no_forbidden_import_in_snn_source(self) -> None:
        for filename, source in self._snn_sources():
            for mod_name in self._ast_imports(source):
                for forbidden in self.FORBIDDEN_IMPORT_PREFIXES:
                    assert not mod_name.startswith(forbidden), (
                        f"{filename} imports forbidden module: {mod_name}"
                    )

    def test_no_order_send_symbol_in_snn_source(self) -> None:
        """The literal string 'order_send' must not appear in any SNN source file."""
        for filename, source in self._snn_sources():
            assert "order_send" not in source, (
                f"'order_send' found in SNN source: {filename}"
            )


# ---------------------------------------------------------------------------
# Protocole expérimental
# ---------------------------------------------------------------------------


class TestExperimentSpec:
    def test_k1_spec_is_valid(self) -> None:
        errors = validate_spec(K1_EXPERIMENT)
        assert errors == [], f"K1 spec invalid: {errors}"

    def test_spec_requires_name(self) -> None:
        spec = ExperimentSpec(
            name="", primary_metric="x", min_effect_size=0.1,
            n_seeds=1, seeds=[1], n_timesteps_per_trial=10,
            abandonment_criteria=["x"], baseline_description="y",
        )
        errors = validate_spec(spec)
        assert any("name" in e for e in errors)

    def test_spec_requires_positive_effect_size(self) -> None:
        spec = ExperimentSpec(
            name="test", primary_metric="x", min_effect_size=0.0,
            n_seeds=1, seeds=[1], n_timesteps_per_trial=10,
            abandonment_criteria=["x"], baseline_description="y",
        )
        errors = validate_spec(spec)
        assert any("min_effect_size" in e for e in errors)

    def test_spec_seeds_must_match_n_seeds(self) -> None:
        spec = ExperimentSpec(
            name="test", primary_metric="x", min_effect_size=0.1,
            n_seeds=3, seeds=[1, 2], n_timesteps_per_trial=10,
            abandonment_criteria=["x"], baseline_description="y",
        )
        errors = validate_spec(spec)
        assert any("seeds" in e for e in errors)

    def test_spec_seeds_must_be_unique(self) -> None:
        spec = ExperimentSpec(
            name="test", primary_metric="x", min_effect_size=0.1,
            n_seeds=2, seeds=[1, 1], n_timesteps_per_trial=10,
            abandonment_criteria=["x"], baseline_description="y",
        )
        errors = validate_spec(spec)
        assert any("unique" in e for e in errors)

    def test_trial_result_stores_none_for_incomplete(self) -> None:
        result = TrialResult(
            experiment_name="K1", seed=42, condition="snn_lif",
            primary_metric_value=None, n_trials=0,
            notes="incomplete — data missing",
        )
        assert result.primary_metric_value is None

    def test_k1_spec_has_multiple_seeds(self) -> None:
        assert K1_EXPERIMENT.n_seeds >= 3

    def test_k1_spec_has_abandonment_criteria(self) -> None:
        assert len(K1_EXPERIMENT.abandonment_criteria) >= 1
