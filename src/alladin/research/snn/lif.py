"""
Leaky Integrate-and-Fire (LIF) neuron — Lot K1.

Deterministic, seed-reproducible. No stochastic elements unless explicitly seeded.
Isolated from the execution path.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LIFParams:
    """Parameters for a population of LIF neurons."""

    n_neurons: int = 10
    tau_m: float = 20.0       # membrane time constant (ms)
    v_rest: float = -65.0     # resting potential (mV)
    v_thresh: float = -50.0   # spike threshold (mV)
    v_reset: float = -65.0    # reset potential after spike (mV)
    r_membrane: float = 10.0  # membrane resistance (MOhm)
    dt: float = 1.0           # time step (ms)
    refractory_steps: int = 2 # absolute refractory period in time steps


@dataclass
class LIFState:
    """Mutable state of a LIF population across one timestep."""

    v: list[float]                   # membrane potential per neuron
    refractory_countdown: list[int]  # remaining refractory steps per neuron
    spikes: list[bool]               # spike output this timestep


def make_lif_state(params: LIFParams) -> LIFState:
    """Initialize a LIF population at rest."""
    return LIFState(
        v=[params.v_rest] * params.n_neurons,
        refractory_countdown=[0] * params.n_neurons,
        spikes=[False] * params.n_neurons,
    )


def lif_step(
    state: LIFState,
    current_inputs: list[float],
    params: LIFParams,
) -> LIFState:
    """
    Advance the LIF population by one timestep.

    Args:
        state: Current neuron state (not mutated).
        current_inputs: Input current (nA) per neuron, length == params.n_neurons.
        params: Fixed neuron parameters.

    Returns:
        New LIFState after the step.
    """
    if len(current_inputs) != params.n_neurons:
        raise ValueError(
            f"current_inputs length {len(current_inputs)} != n_neurons {params.n_neurons}"
        )

    new_v: list[float] = []
    new_refractory: list[int] = []
    new_spikes: list[bool] = []

    alpha = params.dt / params.tau_m  # Euler integration factor

    for i in range(params.n_neurons):
        if state.refractory_countdown[i] > 0:
            # Neuron is refractory: clamp at reset, no integration
            new_v.append(params.v_reset)
            new_refractory.append(state.refractory_countdown[i] - 1)
            new_spikes.append(False)
        else:
            # Euler integration: tau_m dv/dt = -(v - v_rest) + R * I
            dv = alpha * (
                -(state.v[i] - params.v_rest) + params.r_membrane * current_inputs[i]
            )
            v_new = state.v[i] + dv

            if v_new >= params.v_thresh:
                new_v.append(params.v_reset)
                new_refractory.append(params.refractory_steps)
                new_spikes.append(True)
            else:
                new_v.append(v_new)
                new_refractory.append(0)
                new_spikes.append(False)

    return LIFState(v=new_v, refractory_countdown=new_refractory, spikes=new_spikes)


def run_lif_population(
    current_sequence: list[list[float]],
    params: LIFParams,
) -> list[list[bool]]:
    """
    Run a LIF population over a sequence of inputs.

    Args:
        current_sequence: List of T timesteps, each a list of n_neurons currents.
        params: Fixed neuron parameters.

    Returns:
        List of T spike patterns (one list[bool] per timestep).
    """
    state = make_lif_state(params)
    spike_train: list[list[bool]] = []

    for currents in current_sequence:
        state = lif_step(state, currents, params)
        spike_train.append(list(state.spikes))

    return spike_train
