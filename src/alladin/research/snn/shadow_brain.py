"""
Shadow Brain — Lot K2.

Un Shadow Brain observe le même flux d'entrée que le Brain actif et produit
des ActionProposals alternatives sans jamais accéder à l'ExecutionEngine,
au Broker ou aux positions réelles.

Invariants :
- Aucun import depuis execution/, brokers/, orchestration/.
- Aucun envoi d'ordre, aucune modification de poids actifs.
- Isolation complète : le Shadow ne peut qu'observer et mémoriser.
- Promotion uniquement via DECISION-020 et les gates existants.
"""

from __future__ import annotations

import json
import math
import statistics
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from alladin.research.snn.encoder import EncoderParams, encode_features
from alladin.research.snn.rstdp import (
    RSTDPParams,
    RSTDPState,
    accumulate_eligibility,
    apply_reward,
    make_rstdp_state,
    readout,
)

# ---------------------------------------------------------------------------
# Structures de données
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ShadowObservation:
    """Vecteur de features normalisées reçu par le Shadow Brain."""

    symbol: str
    cycle_id: str
    features: tuple[float, ...]
    feature_names: tuple[str, ...]
    min_vals: tuple[float, ...]
    max_vals: tuple[float, ...]
    observed_at: datetime

    def __post_init__(self) -> None:
        n = len(self.features)
        if n == 0:
            raise ValueError("features non vide requises")
        if len(self.feature_names) != n or len(self.min_vals) != n or len(self.max_vals) != n:
            raise ValueError("feature_names, min_vals, max_vals doivent avoir la même longueur que features")
        for i, (lo, hi) in enumerate(zip(self.min_vals, self.max_vals, strict=True)):
            if not math.isfinite(lo) or not math.isfinite(hi):
                raise ValueError(f"min/max invalides pour feature {i}")
            if lo >= hi:
                raise ValueError(f"min >= max pour feature {i}")


@dataclass(frozen=True)
class ShadowProposal:
    """ActionProposal produit exclusivement par le Shadow Brain."""

    shadow_id: str
    cycle_id: str
    symbol: str
    action: str          # "LONG" | "SHORT" | "NO_TRADE"
    confidence: float    # [0, 1]
    spike_rate: float    # taux de décharge moyen des neurones de sortie
    produced_at: datetime
    source_version: str = "shadow_brain:k2:1"

    def __post_init__(self) -> None:
        if self.action not in ("LONG", "SHORT", "NO_TRADE"):
            raise ValueError(f"action invalide : {self.action!r}")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence doit être dans [0, 1]")
        if not math.isfinite(self.spike_rate) or self.spike_rate < 0:
            raise ValueError("spike_rate invalide")


@dataclass(frozen=True)
class ShadowOutcome:
    """Résultat réel observé après une proposition Shadow."""

    cycle_id: str
    symbol: str
    actual_return_pct: float    # rendement réel observé
    actual_action: str           # action prise par le Brain actif
    pnl_r: float | None = None  # R-multiple si disponible
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not math.isfinite(self.actual_return_pct):
            raise ValueError("actual_return_pct invalide")


@dataclass(frozen=True)
class ShadowComparison:
    """Résultat de comparaison Shadow vs Brain actif."""

    cycle_id: str
    symbol: str
    shadow_action: str
    active_action: str
    shadow_would_have_been_better: bool | None   # None = indéterminé
    return_diff_pct: float | None                # shadow_return - active_return
    notes: str = ""


# ---------------------------------------------------------------------------
# Métriques d'évaluation
# ---------------------------------------------------------------------------


@dataclass
class ShadowMetrics:
    """Métriques agrégées évaluant la valeur ajoutée potentielle du Shadow Brain."""

    n_proposals: int = 0
    n_outcomes: int = 0
    n_comparable: int = 0
    hit_rate: float | None = None             # proportion de décisions directionnelles correctes
    avg_return_diff_pct: float | None = None  # rendement moyen Shadow - Brain actif
    shadow_sharpe_proxy: float | None = None  # Sharpe des rendements théoriques Shadow
    active_sharpe_proxy: float | None = None  # Sharpe des rendements réels
    is_candidate: bool = False                # True si Shadow dépasse la baseline sur critères définis

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_proposals": self.n_proposals,
            "n_outcomes": self.n_outcomes,
            "n_comparable": self.n_comparable,
            "hit_rate": self.hit_rate,
            "avg_return_diff_pct": self.avg_return_diff_pct,
            "shadow_sharpe_proxy": self.shadow_sharpe_proxy,
            "active_sharpe_proxy": self.active_sharpe_proxy,
            "is_candidate": self.is_candidate,
        }


def _sharpe_proxy(returns: list[float]) -> float | None:
    """Sharpe simplifié sans taux sans risque, retourne None si données insuffisantes."""
    if len(returns) < 2:
        return None
    mean = statistics.mean(returns)
    std = statistics.stdev(returns)
    if std == 0:
        return None
    return mean / std


def _action_return(action: str, actual_return_pct: float) -> float:
    """Rendement théorique si l'action avait été prise (simplifié, sans coûts)."""
    if action == "LONG":
        return actual_return_pct
    if action == "SHORT":
        return -actual_return_pct
    return 0.0  # NO_TRADE


# ---------------------------------------------------------------------------
# Noyau SNN du Shadow Brain
# ---------------------------------------------------------------------------


class ShadowSNN:
    """
    Encodeur + R-STDP strictement isolé du chemin d'exécution.

    Architecture K2 : encode_features → spike trains → readout pondéré → action.
    Les poids sont INDÉPENDANTS des poids du Brain actif.
    L'apprentissage R-STDP utilise les spike trains de l'encodeur directement
    afin de garantir que des spikes existent même pour des features faibles.
    """

    def __init__(
        self,
        encoder_params: EncoderParams | None = None,
        rstdp_params: RSTDPParams | None = None,
        seed: int = 999,
    ) -> None:
        # n_neurons de l'encodeur → n_pre du RSTDP
        self.encoder_params = encoder_params or EncoderParams(n_neurons=8, n_timesteps=15, seed=seed)
        n_pre = self.encoder_params.n_neurons
        self.rstdp_params = rstdp_params or RSTDPParams(n_pre=n_pre, n_post=3, seed=seed)
        self._rstdp_state: RSTDPState = make_rstdp_state(self.rstdp_params, seed=seed)
        self._seed = seed
        self._last_pre_spikes: list[list[bool]] = []

    def forward(self, obs: ShadowObservation) -> tuple[str, float, float]:
        """
        Passe avant : encode → readout RSTDP → action.

        Retourne (action, confidence, spike_rate).
        """
        features_dict = {obs.feature_names[i]: obs.features[i] for i in range(len(obs.features))}
        ranges_dict = {
            obs.feature_names[i]: (obs.min_vals[i], obs.max_vals[i])
            for i in range(len(obs.features))
        }
        encoded: dict[str, list[list[bool]]] = encode_features(features_dict, ranges_dict, self.encoder_params)

        # Concatène les T timesteps de toutes les features (chacune indépendante)
        # Résultat : T_total × n_neurons
        all_timesteps: list[list[bool]] = []
        for spike_train in sorted(encoded):  # tri pour déterminisme
            all_timesteps.extend(encoded[spike_train])

        if not all_timesteps:
            self._last_pre_spikes = []
            return "NO_TRADE", 0.0, 0.0

        self._last_pre_spikes = all_timesteps

        # Taux de décharge global (pré)
        total_spikes = sum(sum(1 for s in step if s) for step in all_timesteps)
        n_total = len(all_timesteps) * len(all_timesteps[0]) if all_timesteps else 1
        spike_rate = total_spikes / max(n_total, 1)

        # Readout pondéré : pre_spikes T × n_pre → scores n_post
        scores = readout(all_timesteps, self._rstdp_state.weights)

        # 3 neurones de sortie → LONG, SHORT, NO_TRADE
        scores_3 = (list(scores) + [0.0, 0.0, 0.0])[:3]
        action_map = ["LONG", "SHORT", "NO_TRADE"]
        best_idx = max(range(3), key=lambda i: scores_3[i])
        action = action_map[best_idx]
        max_score = scores_3[best_idx]
        score_sum = sum(abs(s) for s in scores_3)
        confidence = abs(max_score) / score_sum if score_sum > 0 else 0.0
        confidence = min(max(confidence, 0.0), 1.0)
        return action, confidence, spike_rate

    def learn(self, reward: float) -> None:
        """Applique R-STDP avec la récompense fournie. Ne touche pas aux poids actifs."""
        if not self._last_pre_spikes:
            return
        n_pre = self.rstdp_params.n_pre
        n_post = self.rstdp_params.n_post
        pre = self._last_pre_spikes
        # Pad pre à n_pre colonnes
        pre_padded = [(list(row) + [False] * n_pre)[:n_pre] for row in pre]
        # Post proxy : toujours actif si spike_rate > 0 (simplifié pour K2)
        has_spikes = any(any(row) for row in pre_padded)
        post_padded = [[has_spikes] * n_post for _ in pre_padded]
        self._rstdp_state = accumulate_eligibility(
            self._rstdp_state, pre_padded, post_padded, self.rstdp_params
        )
        self._rstdp_state = apply_reward(self._rstdp_state, reward, self.rstdp_params)


# ---------------------------------------------------------------------------
# Shadow Brain principal
# ---------------------------------------------------------------------------


class ShadowBrain:
    """
    Observateur passif du même flux causal que le Brain actif.

    Invariants :
    - Aucun accès execution, brokers, orchestration.
    - Aucun envoi d'ordre.
    - Les propositions sont persistées localement dans un journal JSON.
    - L'apprentissage R-STDP s'effectue sur des poids indépendants.
    - La promotion vers PROD nécessite un processus humain explicite (DECISION-020).
    """

    def __init__(
        self,
        shadow_id: str,
        journal_path: Path | None = None,
        snn: ShadowSNN | None = None,
    ) -> None:
        if not shadow_id.strip():
            raise ValueError("shadow_id requis")
        self.shadow_id = shadow_id
        self.snn = snn or ShadowSNN(seed=hash(shadow_id) % (2**31))
        self._journal_path = journal_path
        self._proposals: list[ShadowProposal] = []
        self._outcomes: list[ShadowOutcome] = []
        self._comparisons: list[ShadowComparison] = []
        if journal_path is not None:
            self._load_journal()

    # ------------------------------------------------------------------
    # Interface publique
    # ------------------------------------------------------------------

    def observe_and_propose(self, obs: ShadowObservation) -> ShadowProposal:
        """Observe un flux causal et produit une proposition alternative."""
        action, confidence, spike_rate = self.snn.forward(obs)
        proposal = ShadowProposal(
            shadow_id=self.shadow_id,
            cycle_id=obs.cycle_id,
            symbol=obs.symbol,
            action=action,
            confidence=confidence,
            spike_rate=spike_rate,
            produced_at=datetime.now(UTC),
        )
        self._proposals.append(proposal)
        self._persist()
        return proposal

    def register_outcome(self, outcome: ShadowOutcome) -> ShadowComparison | None:
        """
        Enregistre le résultat réel et compare avec la proposition Shadow.

        Retourne une ShadowComparison si une proposition correspondante existe.
        Déclenche l'apprentissage R-STDP avec la récompense dérivée du résultat.
        """
        self._outcomes.append(outcome)
        proposal = self._find_proposal(outcome.cycle_id, outcome.symbol)
        if proposal is None:
            self._persist()
            return None

        shadow_return = _action_return(proposal.action, outcome.actual_return_pct)
        active_return = _action_return(outcome.actual_action, outcome.actual_return_pct)
        return_diff = shadow_return - active_return

        better: bool | None = None if abs(return_diff) < 1e-9 else return_diff > 0

        comparison = ShadowComparison(
            cycle_id=outcome.cycle_id,
            symbol=outcome.symbol,
            shadow_action=proposal.action,
            active_action=outcome.actual_action,
            shadow_would_have_been_better=better,
            return_diff_pct=return_diff,
        )
        self._comparisons.append(comparison)

        # Apprentissage R-STDP : récompense = rendement marché réel (direction marché),
        # borné ±5. Enseigne la direction du marché indépendamment de l'action Shadow.
        reward = max(-5.0, min(5.0, outcome.actual_return_pct / 10.0))
        self.snn.learn(reward)

        self._persist()
        return comparison

    def compute_metrics(self) -> ShadowMetrics:
        """Calcule les métriques d'évaluation sur l'historique complet."""
        n_proposals = len(self._proposals)
        n_outcomes = len(self._outcomes)
        n_comparable = len(self._comparisons)

        metrics = ShadowMetrics(
            n_proposals=n_proposals,
            n_outcomes=n_outcomes,
            n_comparable=n_comparable,
        )

        if not self._comparisons:
            return metrics

        diffs = [c.return_diff_pct for c in self._comparisons if c.return_diff_pct is not None]
        if diffs:
            metrics.avg_return_diff_pct = statistics.mean(diffs)

        better_count = sum(
            1 for c in self._comparisons if c.shadow_would_have_been_better is True
        )
        if n_comparable > 0:
            metrics.hit_rate = better_count / n_comparable

        # Rendements théoriques pour Sharpe
        # Retrouver les outcomes correspondants
        outcome_map = {(o.cycle_id, o.symbol): o for o in self._outcomes}

        shadow_returns: list[float] = []
        active_returns: list[float] = []
        for comp in self._comparisons:
            key = (comp.cycle_id, comp.symbol)
            outcome = outcome_map.get(key)
            if outcome is not None:
                shadow_returns.append(_action_return(comp.shadow_action, outcome.actual_return_pct))
                active_returns.append(_action_return(comp.active_action, outcome.actual_return_pct))

        metrics.shadow_sharpe_proxy = _sharpe_proxy(shadow_returns)
        metrics.active_sharpe_proxy = _sharpe_proxy(active_returns)

        # Candidat si avg_return_diff > 0 ET hit_rate > 0.5 ET au moins 10 comparaisons
        metrics.is_candidate = (
            n_comparable >= 10
            and (metrics.avg_return_diff_pct or 0) > 0
            and (metrics.hit_rate or 0) > 0.5
        )

        return metrics

    def proposals(self) -> list[ShadowProposal]:
        return list(self._proposals)

    def outcomes(self) -> list[ShadowOutcome]:
        return list(self._outcomes)

    def comparisons(self) -> list[ShadowComparison]:
        return list(self._comparisons)

    # ------------------------------------------------------------------
    # Persistance JSON légère
    # ------------------------------------------------------------------

    def _find_proposal(self, cycle_id: str, symbol: str) -> ShadowProposal | None:
        for p in reversed(self._proposals):
            if p.cycle_id == cycle_id and p.symbol == symbol:
                return p
        return None

    def _persist(self) -> None:
        if self._journal_path is None:
            return
        self._journal_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "shadow_id": self.shadow_id,
            "proposals": [
                {
                    "shadow_id": p.shadow_id,
                    "cycle_id": p.cycle_id,
                    "symbol": p.symbol,
                    "action": p.action,
                    "confidence": p.confidence,
                    "spike_rate": p.spike_rate,
                    "produced_at": p.produced_at.isoformat(),
                    "source_version": p.source_version,
                }
                for p in self._proposals
            ],
            "outcomes": [
                {
                    "cycle_id": o.cycle_id,
                    "symbol": o.symbol,
                    "actual_return_pct": o.actual_return_pct,
                    "actual_action": o.actual_action,
                    "pnl_r": o.pnl_r,
                    "recorded_at": o.recorded_at.isoformat(),
                }
                for o in self._outcomes
            ],
        }
        self._journal_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _load_journal(self) -> None:
        if self._journal_path is None or not self._journal_path.exists():
            return
        try:
            data = json.loads(self._journal_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        for row in data.get("proposals", []):
            try:
                self._proposals.append(
                    ShadowProposal(
                        shadow_id=row["shadow_id"],
                        cycle_id=row["cycle_id"],
                        symbol=row["symbol"],
                        action=row["action"],
                        confidence=float(row["confidence"]),
                        spike_rate=float(row["spike_rate"]),
                        produced_at=datetime.fromisoformat(row["produced_at"]),
                        source_version=row.get("source_version", "shadow_brain:k2:1"),
                    )
                )
            except (KeyError, ValueError):
                continue
        for row in data.get("outcomes", []):
            try:
                self._outcomes.append(
                    ShadowOutcome(
                        cycle_id=row["cycle_id"],
                        symbol=row["symbol"],
                        actual_return_pct=float(row["actual_return_pct"]),
                        actual_action=row["actual_action"],
                        pnl_r=row.get("pnl_r"),
                        recorded_at=datetime.fromisoformat(row["recorded_at"]),
                    )
                )
            except (KeyError, ValueError):
                continue


class ShadowSlowLoop:
    """SLOW: outcomes, reward, apprentissage et evaluation hors chemin FAST."""

    def __init__(self, brain: ShadowBrain) -> None:
        self.brain = brain

    def process(self, outcomes: Iterable[ShadowOutcome]) -> ShadowMetrics:
        for outcome in outcomes:
            self.brain.register_outcome(outcome)
        return self.brain.compute_metrics()

    def candidate(self) -> bool:
        """Un candidat reste une information; cette API ne promeut jamais de poids."""
        return self.brain.compute_metrics().is_candidate
