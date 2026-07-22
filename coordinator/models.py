"""
coordinator/models.py — Modèles Pydantic du coordinateur.

CAP v1 (CoordinatorDirective) a été retiré : le coordinateur v2 ne transmet
plus de paquet structuré aux agents, il passe par `ToolAgentClient.execute`
(langage naturel) ou `execute_structured` (fonction + args directs). Ce module
ne contient plus de contenu utile à ce jour ; conservé vide pour ne pas casser
un import résiduel éventuel hors du périmètre B.
"""

from __future__ import annotations
