"""Exceptions métier."""

from __future__ import annotations


class AlladinError(Exception):
    """Base de toutes les erreurs ALLADIN."""


class BrokerConnectionError(AlladinError):
    """Terminal/broker injoignable ou non autorisé."""


class ExecutionBlockedError(AlladinError):
    """Exécution refusée par un garde-fou (compte non DEMO, kill switch, ...)."""


class IrreversibleStateError(AlladinError):
    """Tentative de modifier un run dans un état terminal (FAILED/PASSED/KILLED)."""


class ConfigError(AlladinError):
    """Configuration invalide."""
