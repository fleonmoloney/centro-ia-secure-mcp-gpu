"""Detectores heurísticos. Son una mitigación, no una defensa completa:
la barrera fuerte es la política de flujo (policy.py), que no depende de reconocer el ataque."""
from __future__ import annotations

import re
import unicodedata

# Patrones de instrucciones dirigidas al modelo dentro de datos (es/en).
_INJECTION = [
    r"ignor[ae]\s+(todas?\s+)?(las\s+)?(instrucciones|indicaciones)\s+(anteriores|previas)",
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above)\s+(instructions|prompts?)",
    r"olvid[ae]\s+(todo|lo\s+anterior)",
    r"(nuevas?|new)\s+(instrucciones|instructions)\s*:",
    r"(system|sistema)\s*(prompt|message|mensaje)\s*:",
    r"you\s+are\s+now\b",
    r"ahora\s+eres\b",
    r"(env[ií]a|envi[ae]|manda|send|forward|post)\b.{0,80}\b(a|to)\b.{0,60}(@|https?://)",
    r"(no\s+le\s+(digas|avises)|do\s+not\s+(tell|inform))\s+(al\s+)?(usuario|user)",
    r"<\s*/?\s*(system|instructions?|tool_call)\s*>",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _INJECTION]

# Secretos con formato reconocible.
_SECRET = {
    "api_key": re.compile(r"\b(?:sk|pk|api|key)[-_][A-Za-z0-9]{16,}\b"),
    "aws_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "cedula": re.compile(r"\b\d\.\d{3}\.\d{3}-\d\b"),
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
}
_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b‌‍⁠﻿"), None)


def normalize(text: str) -> str:
    """Quita caracteres invisibles y unifica Unicode para que no evadan los patrones."""
    return unicodedata.normalize("NFKC", text).translate(_ZERO_WIDTH)


def injection_hits(text: str) -> list[str]:
    t = normalize(text)
    return [p.pattern for p in _INJECTION_RE if p.search(t)]


def secret_kinds(text: str) -> list[str]:
    t = normalize(text)
    return [k for k, rx in _SECRET.items() if rx.search(t)]


def contains_canary(text: str, canaries: set[str]) -> bool:
    t = normalize(text)
    return any(c in t for c in canaries)
