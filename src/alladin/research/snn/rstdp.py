"""
Reward-modulated Spike-Timing Dependent Plasticity (R-STDP) — Lot K1.

Minimal implementation. Weights are updated after a trial using a
reward signal (compatible with the versioned reward from Lot J).
No mutation of the active Brain. Isolated from the execution path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RSTDPParams:
    """Hyperparameters for R-STDP weight updates."""

    n_pre: int = 10          # pre-synaptic neurons (encoder output)
    n_post: int = 5          # post-synaptic neurons (readout)
    lr_plus: float = 0.01    # learning rate for potentiation (reward > 0)
    lr_minus: float = 0.01   # learning rate for depression (reward < 0)
    w_min: float = 0.0       # minimum weight (hard clip)
    w_max: float = 1.0       # maximum weight (hard clip)
    tau_plus: float = 20.0   # STDP time constant for pre→post (ms)
    tau_minus: float = 20.0  # STDP time constant for post→pre (ms)
    seed: int = 42


@dataclass
class RSTDPState:
    """Mutable weight matrix and eligibility traces."""

    weights: list[list[float]]  # shape [n_post][n_pre]
    eligibility: list[list[float]]  # accumulated eligibility trace, same shape


def make_rstdp_state(params: RSTDPParams, seed: int | None = None) -> RSTDPState:
    """
    Initialize weights uniformly in [w_min, w_max] with a fixed seed.

    Args:
        params: R-STDP parameters.
        seed: Override seed (uses params.seed if None).
    """
    import random
    rng = random.Random(seed if seed is not None else params.seed)
    w_range = params.w_max - params.w_min
    weights = [
        [params.w_min + rng.random() * w_range for _ in range(params.n_pre)]
        for _ in range(params.n_post)
    ]
    eligibility = [
        [0.0 for _ in range(params.n_pre)]
        for _ in range(params.n_post)
    ]
    return RSTDPState(weights=weights, eligibility=eligibility)


def _clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def accumulate_eligibility(
    state: RSTDPState,
    pre_spikes: list[list[bool]],
    post_spikes: list[list[bool]],
    params: RSTDPParams,
) -> RSTDPState:
    """
    Accumulate eligibility traces from pre/post spike trains.

    Simplified STDP: for each (post, pre) pair, if they co-fire within
    a window, add a positive trace; if post fires before pre, add a
    negative trace. Uses an exponential-decay approximation over timesteps.

    Args:
        state: Current R-STDP state (not mutated).
        pre_spikes: T × n_pre spike matrix.
        post_spikes: T × n_post spike matrix.
        params: R-STDP parameters.

    Returns:
        New RSTDPState with updated eligibility traces.
    """
    import math

    n_steps = len(pre_spikes)
    if n_steps == 0:
        return state

    new_elig = [list(row) for row in state.eligibility]

    # Running traces for each neuron: decaying sum of past spikes
    pre_trace = [0.0] * params.n_pre
    post_trace = [0.0] * params.n_post
    decay_pre = math.exp(-params.tau_plus / params.tau_plus)   # = e^-1 per tau_plus step
    decay_post = math.exp(-params.tau_minus / params.tau_minus)

    for t in range(n_steps):
        # Decay traces
        pre_trace = [x * decay_pre for x in pre_trace]
        post_trace = [x * decay_post for x in post_trace]

        # Update traces for spikes this step
        for j in range(params.n_pre):
            if pre_spikes[t][j]:
                pre_trace[j] += 1.0
        for i in range(params.n_post):
            if post_spikes[t][i]:
                post_trace[i] += 1.0

        # Accumulate eligibility
        for i in range(params.n_post):
            if post_spikes[t][i]:
                # post fires: potentiate connections from recently active pre
                for j in range(params.n_pre):
                    new_elig[i][j] += pre_trace[j]
            if len(pre_spikes[t]) > 0:
                for j in range(params.n_pre):
                    if pre_spikes[t][j]:
                        # pre fires: depress connections to recently active post
                        for i2 in range(params.n_post):
                            new_elig[i2][j] -= post_trace[i2]

    return RSTDPState(weights=list(list(row) for row in state.weights), eligibility=new_elig)


def apply_reward(
    state: RSTDPState,
    reward: float,
    params: RSTDPParams,
) -> RSTDPState:
    """
    Apply the reward signal to update weights from eligibility traces,
    then reset eligibility to zero.

    weight_delta = reward > 0 : lr_plus * reward * eligibility
                   reward < 0 : lr_minus * reward * eligibility
    Weights are hard-clipped to [w_min, w_max].

    Args:
        state: Current R-STDP state (not mutated).
        reward: Scalar reward from the versioned reward policy (Lot J).
        params: R-STDP parameters.

    Returns:
        New RSTDPState with updated weights and zeroed eligibility.
    """
    lr = params.lr_plus if reward >= 0 else params.lr_minus
    new_weights = []
    for i in range(params.n_post):
        row = []
        for j in range(params.n_pre):
            delta = lr * reward * state.eligibility[i][j]
            w_new = _clip(state.weights[i][j] + delta, params.w_min, params.w_max)
            row.append(w_new)
        new_weights.append(row)

    zeroed_elig = [[0.0] * params.n_pre for _ in range(params.n_post)]
    return RSTDPState(weights=new_weights, eligibility=zeroed_elig)


def readout(
    pre_spikes: list[list[bool]],
    weights: list[list[float]],
) -> list[float]:
    """
    Linear readout: sum of weighted pre-synaptic spike counts per post neuron.

    Args:
        pre_spikes: T × n_pre spike matrix.
        weights: n_post × n_pre weight matrix.

    Returns:
        Activation per post neuron (float).
    """
    n_post = len(weights)
    if n_post == 0 or not pre_spikes:
        return [0.0] * n_post

    n_pre = len(weights[0])
    # Sum spikes per pre neuron
    pre_counts = [0.0] * n_pre
    for step in pre_spikes:
        for j, s in enumerate(step):
            if s:
                pre_counts[j] += 1.0

    return [
        sum(weights[i][j] * pre_counts[j] for j in range(n_pre))
        for i in range(n_post)
    ]
