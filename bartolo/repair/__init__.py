"""bartolo/repair/ — Sistema de reparació + aprenentatge."""

from bartolo.repair.kb import RepairKB
from bartolo.repair.fallback import _FALLBACK_MAP, _get_fallbacks
from bartolo.repair.anthropic import _read_api_key, _make_anthropic_client, repair_with_anthropic
from bartolo.repair.deepseek import repair_with_deepseek, repair_signature, DEEPSEEK_MODEL, DEEPSEEK_CHAT_URL
from bartolo.repair.debugger import IntelligentDebugger, Diagnosis, RepairResult

__all__ = [
    "RepairKB", "IntelligentDebugger", "Diagnosis", "RepairResult",
    "_FALLBACK_MAP", "_get_fallbacks",
    "_read_api_key", "_make_anthropic_client", "repair_with_anthropic",
    "repair_with_deepseek", "repair_signature", "DEEPSEEK_MODEL", "DEEPSEEK_CHAT_URL",
]
