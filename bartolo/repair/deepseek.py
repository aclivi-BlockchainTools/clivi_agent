"""bartolo/repair/deepseek.py — DeepSeek API client per reparació econòmica d'errors."""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict, List, Optional

import requests

from bartolo.validator import validate_command

DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_CHAT_URL = "https://api.deepseek.com/v1/chat/completions"

# Mapeig de noms d'error comuns a tipus normalitzats
_ERROR_TYPE_MAP = {
    "EADDRINUSE": "port_conflict",
    "ECONNREFUSED": "network_error",
    "command not found": "missing_dependency",
    "No such file": "missing_dependency",
    "ModuleNotFoundError": "missing_dependency",
    "ImportError": "missing_dependency",
    "Permission denied": "permission_error",
    "EACCES": "permission_error",
    "ENOENT": "missing_dependency",
    "version": "wrong_version",
    "timeout": "network_error",
    "Killed": "other",
    "out of memory": "other",
}


def repair_signature(stack: str, error_message: str) -> str:
    """Genera una signatura normalitzada per a la KB de reparacions.

    Normalitza números → N, hex → HEX, paths → PATH perquè patrons
    d'error similars generin la mateixa signatura.
    """
    normalized = re.sub(r'\d+', 'N', error_message.lower().strip())
    normalized = re.sub(r'0x[0-9a-f]+', 'HEX', normalized)
    normalized = re.sub(r'/[^\s]+', 'PATH', normalized)
    return f"{stack}::{hashlib.md5(normalized.encode()).hexdigest()[:16]}"


def _extract_error_type(stderr: str) -> str:
    """Extreu el tipus d'error normalitzat del stderr."""
    stderr_lower = stderr.lower()
    for pattern, error_type in _ERROR_TYPE_MAP.items():
        if pattern.lower() in stderr_lower:
            return error_type
    return "other"


def _read_api_key() -> Optional[str]:
    """Llegeix l'API key de DeepSeek des de l'entorn o secrets.json."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if key:
        return key
    secrets_path = os.path.expanduser("~/.universal-agent/secrets.json")
    try:
        secrets = json.loads(open(secrets_path, encoding="utf-8").read())
        return secrets.get("deepseek_api_key")
    except Exception:
        return None


def repair_with_deepseek(
    stack: str,
    error: str,
    step_command: str,
    repo_context: Dict[str, Any],
    api_key: Optional[str] = None,
) -> Optional[str]:
    """Envia l'error a DeepSeek i retorna la comanda corregida, o None.

    Args:
        stack: Tipus de stack (node, python, go...)
        error: Stderr complet de l'error
        step_command: Comanda original que ha fallat
        repo_context: Dict amb root, manifests, missing_deps
        api_key: API key de DeepSeek (opcional, llegeix de l'entorn si no)

    Returns:
        Comanda bash corregida o None si DeepSeek no pot resoldre-ho.
    """
    key = api_key or _read_api_key()
    if not key:
        return None

    manifests = repo_context.get("manifests", [])
    manifests_str = ", ".join(manifests[:5]) if manifests else "cap"
    root = repo_context.get("root", "")
    missing = repo_context.get("missing_deps", [])
    missing_str = f"\nDependències del sistema que falten: {', '.join(missing)}" if missing else ""

    system_prompt = (
        f"Ets un expert en desplegar repositoris a Linux.\n"
        f"Stack detectat: {stack}\n"
        f"Arrel del repo: {root}\n"
        f"Fitxers principals: {manifests_str}{missing_str}\n"
        f"Regles: sense sudo, sense comandes destructives, cwd fix, només Linux.\n"
        f"IMPORTANT: Respon NOMÉS amb un JSON vàlid: {{\"command\": \"<comanda>\", \"reason\": \"<explicació>\"}}.\n"
        f"El camp 'command' ha de ser UNA sola comanda bash executable, sense text introductori.\n"
        f"Exemples vàlids: 'pip install requests', 'npm install', 'sudo apt-get install -y pkg'.\n"
        f"No facis servir cometes dobles dins la comanda — usa cometes simples si cal."
    )

    user_prompt = (
        f"La comanda ha fallat: `{step_command}`\n"
        f"Error:\n{error[-2000:]}\n\n"
        f"Proposa UNA comanda bash corregida per solucionar l'error."
    )

    try:
        res = requests.post(
            DEEPSEEK_CHAT_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={
                "model": DEEPSEEK_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.2,
                "max_tokens": 256,
            },
            timeout=30,
        )
        res.raise_for_status()
        data = res.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            return None

        # Extreure JSON de la resposta
        match = re.search(r'\{[^}]+\}', content, re.DOTALL)
        if not match:
            return None

        parsed = json.loads(match.group())
        command = parsed.get("command", "").strip()
        if not command:
            return None

        # Neteja: elimina cometes, prefixos conversacionals
        command = command.strip().strip('"').strip("'")
        if ":" in command and command.split(":")[0].strip().count(" ") < 3:
            # Podria ser "Per arreglar: command"
            parts = command.split(":", 1)
            if len(parts[0].split()) <= 3:
                command = parts[1].strip()

        # Validar la comanda abans de retornar-la
        try:
            validate_command(command)
        except Exception:
            return None

        return command
    except Exception:
        return None
