"""Normalização de nome de alimento para lookup no catálogo.

Regras (MVP): remove acentos, lowercase, colapsa espaços/hífens em `_`,
descarta plurais simples ("s"/"es") no fim quando o token > 3 caracteres.
Determinístico — se mudar, precisa regerar índices/aliases.
"""

from __future__ import annotations

import re
import unicodedata

_WHITESPACE = re.compile(r"[\s\-]+")
_NON_WORD = re.compile(r"[^a-z0-9_]+")


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _singularize(token: str) -> str:
    if len(token) <= 3:
        return token
    if token.endswith("oes") or token.endswith("aes") or token.endswith("aos"):
        return token[:-3] + "ao"
    if token.endswith("res"):
        return token[:-2]
    if token.endswith("is") and len(token) > 4:
        return token[:-2] + "l"
    if token.endswith("ns"):
        return token[:-2] + "m"
    if token.endswith("es") and not token.endswith("des"):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def normalize_name(name: str) -> str:
    if not name:
        return ""
    stripped = _strip_accents(name).lower().strip()
    slug = _WHITESPACE.sub("_", stripped)
    slug = _NON_WORD.sub("", slug)
    parts = [_singularize(p) for p in slug.split("_") if p]
    return "_".join(parts)
