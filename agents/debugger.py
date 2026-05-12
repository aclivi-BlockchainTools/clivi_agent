"""agents/debugger.py — Compatibility shim.
Re-exports from bartolo.repair modules so existing code and tests continue working.
"""

from bartolo.repair.debugger import (
    IntelligentDebugger,
    RepairResult,
    Diagnosis,
    _extract_bash_command,
    _sanitize_quotes,
    _tail,
    _CONVERSATIONAL_PREFIXES,
)
from bartolo.repair.kb import RepairKB
from bartolo.repair.anthropic import _read_api_key, _make_anthropic_client
