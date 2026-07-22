import subprocess
import sys
import zipfile
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_wheel_embeds_manifest_and_packages(tmp_path: Path):
    # Build sans isolation (utilise le venv courant, pas de réseau).
    r = subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(tmp_path),
            ".",
        ],
        cwd=str(_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0, r.stderr
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, r.stdout
    names = zipfile.ZipFile(wheels[0]).namelist()
    # fichier de données runtime critique
    assert any(n.endswith("agents/manifests/crowdsec.yml") for n in names), names[:20]
    # packages livrés
    for pkg in ("core/", "coordinator/", "agents/", "clients/"):
        assert any(n.startswith(pkg) for n in names), pkg
    # tests exclus du wheel
    assert not any(n.startswith("tests/") for n in names)
