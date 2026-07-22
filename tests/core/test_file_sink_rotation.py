import json
from pathlib import Path

from core.audit.file_sink import FileAuditSink
from core.audit.sink import AuditEntry

UNBOUNDED_ENTRIES = 50
ROTATION_ENTRIES = 60
BACKUP_COUNT = 2
MAX_FILES = BACKUP_COUNT + 1  # Main file + backup_count backups


def _entry(i: int) -> AuditEntry:
    return AuditEntry(event="executed", capability="crowdsec.ban_ip", effect="allow",
                      rule_reason="r", args={"ip": f"IP_{i}"})


def test_unbounded_when_max_bytes_zero(tmp_path: Path):
    p = tmp_path / "audit.jsonl"
    sink = FileAuditSink(p)  # défaut: pas de rotation
    for i in range(UNBOUNDED_ENTRIES):
        sink.write(_entry(i))
    assert len(p.read_text(encoding="utf-8").splitlines()) == UNBOUNDED_ENTRIES
    assert not (tmp_path / "audit.jsonl.1").exists()


def test_rotation_bounds_disk(tmp_path: Path):
    p = tmp_path / "audit.jsonl"
    sink = FileAuditSink(p, max_bytes=300, backup_count=BACKUP_COUNT)
    for i in range(ROTATION_ENTRIES):
        sink.write(_entry(i))
    # rétention bornée : au plus backup_count sauvegardes, pas de .3
    assert p.exists()
    assert not (tmp_path / "audit.jsonl.3").exists()
    existing = [p] + [
        tmp_path / f"audit.jsonl.{n}" for n in (1, 2)
        if (tmp_path / f"audit.jsonl.{n}").exists()
    ]
    assert len(existing) <= MAX_FILES
    # chaque fichier reste du JSONL valide et ne porte aucune valeur réelle
    for f in existing:
        for line in f.read_text(encoding="utf-8").splitlines():
            obj = json.loads(line)
            assert obj["args"]["ip"].startswith("IP_")
    # la dernière entrée écrite est dans le fichier courant
    assert f"IP_{ROTATION_ENTRIES - 1}" in p.read_text(encoding="utf-8")
