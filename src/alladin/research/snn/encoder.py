"""
Sensory encoder — Lot K1.

Deterministic conversion of scalar features to spike trains.
Rate coding: firing probability proportional to normalized feature value.
Uses explicit seed for reproducibility. No lookahead: only uses present/past data.
Isolated from the execution path.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class EncoderParams:
    """Parameters for the rate-coding encoder."""

    n_neurons: int = 10        # output neurons per feature
    n_timesteps: int = 20      # spike train length per feature value
    max_rate: float = 100.0    # maximum firing rate in Hz; each timestep = 1 ms (dt=1ms implied)
    seed: int = 42


def encode_feature(
    value: float,
    min_val: float,
    max_val: float,
    params: EncoderParams,
) -> list[list[bool]]:
    """
    Encode a single scalar feature as a spike train using rate coding.

    The feature is normalized to [0, 1] relative to [min_val, max_val].
    Each neuron fires independently with probability per timestep:
        p_fire = clamp(normalized * max_rate / 1000.0, 0, 1)
    where max_rate is in Hz and each timestep is implicitly 1 ms (dt=1ms).
    At max_rate=100 Hz: p_fire_max = 0.10 per timestep.
    At max_rate=1000 Hz: p_fire_max = 1.0 per timestep (deterministic full firing).

    Args:
        value: Current feature value (must be in [min_val, max_val]).
        min_val: Feature minimum (for normalization).
        max_val: Feature maximum (for normalization).
        params: Encoder parameters including seed.

    Returns:
        Spike train: list of n_timesteps, each a list[bool] of length n_neurons.
    """
    if max_val <= min_val:
        raise ValueError(f"max_val ({max_val}) must be > min_val ({min_val})")

    # Clamp then normalize
    value_clamped = max(min_val, min(max_val, value))
    normalized = (value_clamped - min_val) / (max_val - min_val)  # [0, 1]

    # Firing probability per timestep per neuron.
    # max_rate [Hz] * dt [s] = max_rate / 1000.0 (dt = 1 ms implied).
    p_fire = min(1.0, max(0.0, normalized * params.max_rate / 1000.0))

    rng = random.Random(params.seed)
    spike_train: list[list[bool]] = []
    for _ in range(params.n_timesteps):
        spikes = [rng.random() < p_fire for _ in range(params.n_neurons)]
        spike_train.append(spikes)

    return spike_train


def encode_features(
    features: dict[str, float],
    feature_ranges: dict[str, tuple[float, float]],
    params: EncoderParams,
) -> dict[str, list[list[bool]]]:
    """
    Encode a dictionary of named features.

    Each feature gets its own independent spike train.
    Seeds are derived deterministically from the base seed + feature index
    to guarantee reproducibility regardless of dict ordering.

    Args:
        features: Feature name → current value.
        feature_ranges: Feature name → (min, max) normalization range.
        params: Encoder parameters.

    Returns:
        Dict of feature name → spike train.

    Raises:
        KeyError: If a feature has no range defined.
    """
    encoded: dict[str, list[list[bool]]] = {}
    for idx, name in enumerate(sorted(features)):  # sorted: deterministic order
        if name not in feature_ranges:
            raise KeyError(f"No range defined for feature '{name}'")
        min_val, max_val = feature_ranges[name]
        per_feature_params = EncoderParams(
            n_neurons=params.n_neurons,
            n_timesteps=params.n_timesteps,
            max_rate=params.max_rate,
            seed=params.seed + idx,
        )
        encoded[name] = encode_feature(features[name], min_val, max_val, per_feature_params)
    return encoded


def spike_counts(spike_train: list[list[bool]]) -> list[int]:
    """Return total spike count per neuron across all timesteps."""
    if not spike_train:
        return []
    n = len(spike_train[0])
    counts = [0] * n
    for step in spike_train:
        for i, s in enumerate(step):
            if s:
                counts[i] += 1
    return counts
