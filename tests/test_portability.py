"""Garde-fou de portabilité : les imports du runtime restent légers.

Vérifie, dans un sous-process isolé (donc sans le `conftest.py` de test), que
`import agents`, `import clients` et `import coordinator.app` ne chargent
aucune dépendance lourde (torch/vllm/unsloth) dans `sys.modules`. Ces libs
ne doivent être importées que dans les points d'entrée qui en ont réellement
besoin (chargement paresseux), pas au simple import du package.
"""

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _import_in_subprocess(module_csv: str) -> subprocess.CompletedProcess:
    code = (
        "import sys\n"
        f"import {module_csv}\n"
        "heavy = {'torch', 'vllm', 'unsloth'} & set(sys.modules)\n"
        "assert not heavy, f'deps lourdes importees au chargement: {heavy}'\n"
    )
    return subprocess.run([sys.executable, "-c", code], cwd=str(_ROOT),
                          capture_output=True, text=True, check=False)


def test_import_agents_is_light():
    r = _import_in_subprocess("agents")
    assert r.returncode == 0, r.stderr


def test_import_clients_is_light():
    r = _import_in_subprocess("clients")
    assert r.returncode == 0, r.stderr


def test_import_coordinator_app_is_light():
    r = _import_in_subprocess("coordinator.app")
    assert r.returncode == 0, r.stderr
