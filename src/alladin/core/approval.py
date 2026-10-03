"""Jeton d'approbation : seul le RiskEngine / ExecutionService peut en émettre.

Un broker refuse tout ordre qui ne porte pas un jeton valide, frais, et cohérent avec la
requête (symbole, volume). Un agent n'a aucune référence vers un broker ni vers ce module
(vérifié par test d'architecture) : il ne peut donc pas envoyer d'ordre, même par accident.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Literal

from alladin.core.errors import ExecutionBlockedError

if TYPE_CHECKING:
    from alladin.core.models import OrderRequest

_ISSUER = object()
TOKEN_TTL = timedelta(seconds=60)


@dataclass(frozen=True)
class ApprovalToken:
    kind: Literal["OPEN", "CLOSE", "MODIFY"]
    run_id: str
    symbol: str
    volume: float
    issued_at: datetime
    intent_id: str | None = None
    _issuer: object = field(default=None, repr=False, compare=False)
    request_snapshot: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._issuer is not _ISSUER:
            raise ExecutionBlockedError(
                "ApprovalToken ne peut être émis que par le RiskEngine/ExecutionService"
            )


def issue_open_token(run_id: str, intent_id: str, symbol: str, volume: float) -> ApprovalToken:
    """Appelé uniquement par RiskEngine.evaluate() après approbation."""
    return ApprovalToken("OPEN", run_id, symbol, volume, datetime.now(UTC), intent_id, _ISSUER)


def issue_close_token(run_id: str, symbol: str, volume: float) -> ApprovalToken:
    """Appelé uniquement par ExecutionService (fermeture = réduction de risque)."""
    return ApprovalToken("CLOSE", run_id, symbol, volume, datetime.now(UTC), None, _ISSUER)


def issue_position_token(
    run_id: str, action: Literal["CLOSE", "MODIFY"], proposal_id: str,
    symbol: str, volume: float, *, request: OrderRequest,
) -> ApprovalToken:
    if (request.action.value != action or request.symbol != symbol or request.volume != volume
            or request.position_ticket is None or request.position_ticket <= 0):
        raise ExecutionBlockedError("requête de gestion incohérente — refusée")
    return ApprovalToken(action, run_id, symbol, volume, datetime.now(UTC), proposal_id, _ISSUER,
                         request.model_dump_json())


def verify_token(request: OrderRequest, token: ApprovalToken | None, *, now: datetime | None = None) -> None:
    """Lève ExecutionBlockedError si le jeton est absent, périmé ou incohérent."""
    if not isinstance(token, ApprovalToken) or token._issuer is not _ISSUER:
        raise ExecutionBlockedError("ordre sans approbation du RiskEngine — refusé")
    now = now or datetime.now(UTC)
    if now - token.issued_at > TOKEN_TTL:
        raise ExecutionBlockedError("approbation périmée — refusé")
    if token.kind != request.action.value:
        raise ExecutionBlockedError("type d'approbation incohérent avec l'ordre — refusé")
    if token.symbol != request.symbol or abs(token.volume - request.volume) > 1e-9:
        raise ExecutionBlockedError("l'ordre diffère de ce que le RiskEngine a approuvé — refusé")
    if token.request_snapshot is not None and token.request_snapshot != request.model_dump_json():
        raise ExecutionBlockedError("la requête de gestion diffère de l'approbation — refusée")
    if request.action.value == "MODIFY" and token.request_snapshot is None:
        raise ExecutionBlockedError("modification sans approbation de la requête complète — refusée")
    if request.action.value == "OPEN" and request.stop_loss is None:
        raise ExecutionBlockedError("NO SL — ordre refusé")
