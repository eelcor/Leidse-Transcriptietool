"""Onvoorspelbare, hoge-entropie tokens voor sessie- en verslag-id's.

Deze id is de enige sleutel tot de data en wordt als geheim behandeld.
"""
from __future__ import annotations

import secrets


def new_token(nbytes: int = 32) -> str:
    # ~43 tekens URL-safe base64 = 256 bits entropie.
    return secrets.token_urlsafe(nbytes)
