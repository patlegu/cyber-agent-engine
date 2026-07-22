import subprocess
import sys
from pathlib import Path

from clients.tool_call_schema import TOOL_CALL_SCHEMA

_ROOT = Path(__file__).resolve().parents[2]


def test_schema_is_a_dict():
    assert isinstance(TOOL_CALL_SCHEMA, dict)
    assert TOOL_CALL_SCHEMA  # non vide


def test_importing_schema_does_not_pull_torch():
    code = (
        "import sys; import clients.tool_call_schema; "
        "assert 'torch' not in sys.modules and 'vllm' not in sys.modules"
    )
    r = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
