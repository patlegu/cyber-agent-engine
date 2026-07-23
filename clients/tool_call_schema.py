# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schéma JSON des tool_calls — module neutre, sans dépendance lourde.

Extrait de native_vllm_client.py pour qu'importer le schéma (ex. dans base.py)
ne charge jamais torch/vllm.
"""

from __future__ import annotations

TOOL_CALL_SCHEMA: dict = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "name":      {"type": "string"},
            "arguments": {"type": "object"},
        },
        "required": ["name", "arguments"],
    },
    "minItems": 1,
    "maxItems": 1,
}
