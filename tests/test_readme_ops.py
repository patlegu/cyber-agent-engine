from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def test_english_readme_documents_ops():
    en = (_ROOT / "README.md").read_text(encoding="utf-8")
    assert "COORDINATOR_AUDIT_MAX_BYTES" in en      # rotation audit
    assert "AGENT_SERVERS" in en                     # multi-serveur
    assert "Dockerfile.gpu" in en                    # image GPU
    assert "policy.example.yml" in en and "source" in en.lower()  # note wheel/source


def test_french_readme_documents_ops():
    fr = (_ROOT / "README.fr.md").read_text(encoding="utf-8")
    assert "COORDINATOR_AUDIT_MAX_BYTES" in fr
    assert "AGENT_SERVERS" in fr
    assert "Dockerfile.gpu" in fr
