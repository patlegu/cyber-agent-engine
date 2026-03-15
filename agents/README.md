# Agents-Outils pour Sécurité Réseau

Agents spécialisés pour **Stormshield**, **OPNsense** et **CrowdSec**.

## Quick Start

### Installation

```bash
cd lora-factory
pip install -r requirements.txt
```

### Utilisation basique

```python
from factory.agents import create_agent

# Créer un agent
agent = create_agent(
    tool_type="stormshield",  # ou "opnsense", "crowdsec"
    model_path="models/stormshield_lora"
)

# Exécuter une requête
result = await agent.execute(
    request="Bloque l'IP 192.168.1.100",
    context={"alert_type": "bruteforce", "severity": "high"}
)

# Vérifier le résultat
if result.success:
    print(f"✅ {result.function}({result.args})")
    print(f"   Résultat: {result.result}")
    print(f"   Temps: {result.execution_time_ms}ms")
```

## Agents disponibles

### StormshieldAgent
Firewall Stormshield SNS - 7 fonctions (block_ip, create_filter_rule, ...)

### OPNsenseAgent
Firewall OPNsense - 7 fonctions (create_firewall_rule, reload_filter, ...)

### CrowdSecAgent
CrowdSec IDPS - 6 fonctions (ban_ip, get_decisions, get_alerts, ...)

## Entraînement

```bash
# 1. Préparer le dataset (150-300 traces)
# Voir data/examples/ pour des exemples

# 2. Entraîner
python scripts/train_tool_agent.py \
    --tool stormshield \
    --dataset data/examples/stormshield_tool_traces.jsonl \
    --output models/stormshield_lora \
    --epochs 3 \
    --rank 16

# 3. Tester
python scripts/test_tool_agent.py \
    --tool stormshield \
    --model models/stormshield_lora
```

## Métriques cibles

| Métrique | Seuil | Critique |
|----------|-------|----------|
| FNR | < 3% | ✅ |
| Précision | > 95% | ✅ |
| Latence | < 200ms | ⚠️ |

## Documentation complète

- **[FIREWALL_AGENTS_GUIDE.md](../../docs/FIREWALL_AGENTS_GUIDE.md)** - Guide complet
- **[HYBRID_ARCHITECTURE_GUIDE.md](../../docs/HYBRID_ARCHITECTURE_GUIDE.md)** - Architecture
- **[data/examples/](../../data/examples/)** - Datasets d'exemple

## Architecture

```
factory/agents/
├── __init__.py           # Exports publics
├── tool_agents.py        # Classe de base + 3 agents
└── README.md             # Ce fichier

scripts/
├── train_tool_agent.py   # Entraînement
└── test_tool_agent.py    # Test interactif

data/examples/
├── stormshield_tool_traces.jsonl
├── opnsense_tool_traces.jsonl
└── crowdsec_tool_traces.jsonl
```

## Flux d'exécution

```
Requête ("Bloque l'IP X")
    ↓
LoRA décide → {function: "block_ip", args: {"ip": "X"}}
    ↓
Validation fonction
    ↓
Appel API réel
    ↓
ToolResult (success, result, latency)
```

## Exemple complet

```python
import asyncio
from factory.agents import create_agent

async def main():
    # Créer les agents
    stormshield = create_agent("stormshield", "models/stormshield_lora")
    crowdsec = create_agent("crowdsec", "models/crowdsec_lora")

    # Workflow: CrowdSec détecte → Stormshield bloque

    # 1. Consulter les alertes CrowdSec
    alerts = await crowdsec.execute(
        "Montre les alertes SSH bruteforce récentes"
    )

    # 2. Bloquer les IPs sur Stormshield
    for alert in alerts.result['alerts']:
        ip = alert['source']['ip']
        block = await stormshield.execute(
            f"Bloque l'IP {ip}",
            context={"source": "crowdsec", "scenario": alert['scenario']}
        )
        print(f"✅ {ip} bloquée en {block.execution_time_ms}ms")

asyncio.run(main())
```

## Tests

```bash
# Unitaires
pytest tests/test_tool_agents.py -v

# Interactif
python scripts/test_tool_agent.py --tool stormshield --model models/stormshield_lora
```

## Bonnes pratiques

### ✅ À faire
- FNR < 3% (CRITIQUE pour sécurité)
- Dataset ciblé 150-300 traces
- Rang LoRA petit (8-16) pour latence
- Monitoring en production (FNR, latence)

### ❌ À éviter
- Dataset > 500 traces (probablement du raisonnement)
- Rang LoRA > 32 (trop lent)
- Ignorer les FN en production
- Pas de validation du dataset avant entraînement
