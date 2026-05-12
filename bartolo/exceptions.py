"""Jerarquia d'excepcions de Bartolo.

Totes hereten d'AgentError per compatibilitat enrere amb el codi existent
que captura AgentError.
"""


class AgentError(Exception):
    """Excepció base per a tots els errors de Bartolo."""
    pass


class DetectorError(AgentError):
    """Errors de detecció de stack (manifests no parsejables, etc.)."""
    pass


class ValidationError(AgentError):
    """Errors de validació de comandes (comanda buida, prefix no permès, patró bloquejat)."""
    pass


class ProvisionerError(AgentError):
    """Errors de provisionament de BD o infraestructura."""
    pass


class PreflightError(AgentError):
    """Errors de pre-flight check (deps del sistema, espai, ports)."""
    pass


class StepExecutionError(AgentError):
    """Errors d'execució d'un pas en runtime."""
    pass
