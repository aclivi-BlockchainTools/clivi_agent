"""bartolo/repair/anthropic.py — Anthropic API client per repair fallback."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

_SECRETS_PATH = Path.home() / ".universal-agent" / "secrets.json"


def _read_api_key() -> Optional[str]:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    key_file = _SECRETS_PATH.parent / "anthropic_api_key"
    if key_file.exists():
        val = key_file.read_text(encoding="utf-8").strip()
        if val:
            return val
    try:
        secrets = json.loads(_SECRETS_PATH.read_text(encoding="utf-8"))
        # El dashboard guarda com ANTHROPIC_API_KEY, el codi antic usava anthropic_api_key
        return secrets.get("ANTHROPIC_API_KEY") or secrets.get("anthropic_api_key")
    except Exception:
        return None


def _make_anthropic_client(api_key: str) -> Any:
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _extract_bash_command(raw: str) -> Optional[str]:
    """Extreu una comanda bash neta del text generat pel model."""
    if not raw or not raw.strip():
        return None
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    if not lines:
        return None
    for line in lines:
        lower = line.lower()
        # Skip conversational prefixes (Catalan and English)
        conversational = [
            "per arreglar-ho prova:", "per assegurar-te", "per solucionar",
            "per verificar", "per comprovar", "la solució és", "pots provar",
            "prova amb", "executa:", "executa", "cal fer", "caldria",
            "has de fer", "podries fer", "intenta amb", "intenta",
            "suggereixo", "recomano", "to fix this", "try running",
            "try:", "run:", "you should", "you can", "the fix is",
            "the solution is", "i recommend", "let's try", "we need to",
            "first,", "then,", "finally,",
        ]
        if any(lower.startswith(p) for p in conversational):
            continue
        words = line.split()
        if len(words) >= 4 and all(not w.startswith("-") and "/" not in w for w in words):
            has_known_cmd = any(
                w in {"pip", "npm", "yarn", "pnpm", "docker", "git", "make", "cargo",
                      "go", "deno", "mix", "dotnet", "python", "python3", "node", "npx",
                      "uvicorn", "streamlit", "flask", "django-admin", "bash", "sh",
                      "nc", "curl", "wget", "apt", "apt-get", "systemctl", "kill"}
                for w in words
            )
            if not has_known_cmd:
                continue
        return line
    return lines[0]


def repair_with_anthropic(
    step: Any,
    prior_attempts: List[Dict[str, Any]],
    stack: str,
    kb_md: str,
    system_prompt_fn: Any,
    api_key: Optional[str] = None,
) -> Optional[str]:
    """
    Fallback: asks Claude (Anthropic API) for a repair command after Ollama exhaustion.
    Returns the command string, or None if unavailable or API call fails.
    """
    key = api_key or _read_api_key()
    if not key:
        return None
    try:
        client = _make_anthropic_client(key)
    except ImportError:
        return None

    system_prompt = system_prompt_fn(stack, kb_md)

    messages: List[Dict[str, Any]] = []
    for a in prior_attempts:
        messages.append({"role": "user", "content": json.dumps({
            "attempt": a["attempt"],
            "tried_command": a["command"],
            "returncode": a["returncode"],
            "stderr": a["stderr_tail"],
        }, ensure_ascii=False)})
        messages.append({"role": "assistant",
                         "content": f"(intent {a['attempt']} ha fallat, cal una altra solució)"})

    messages.append({"role": "user", "content": (
        f"Ollama ha esgotat {len(prior_attempts)} intents sense èxit. "
        f"Necessito UNA comanda shell alternativa per solucionar-ho. "
        f"Respon NOMÉS en JSON: {{\"command\": \"...\", \"reason\": \"...\"}}"
    )})

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            system=[{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=messages,
        )
        raw = response.content[0].text.strip()
        match = re.search(r'\{[^}]+\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            command = _extract_bash_command(data.get("command", ""))
            if command:
                return command
    except Exception:
        pass
    return None
