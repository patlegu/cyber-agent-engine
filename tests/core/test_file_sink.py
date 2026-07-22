import json
from pathlib import Path

from core.audit.file_sink import FileAuditSink
from core.audit.sink import AuditEntry


def _entry(cap: str = "crowdsec.ban_ip") -> AuditEntry:
    return AuditEntry(event="executed", capability=cap, effect="allow",
                      rule_reason="r", args={"ip": "IP_1"})


def test_appends_one_json_line_per_entry(tmp_path: Path):
    p = tmp_path / "audit.jsonl"
    sink = FileAuditSink(p)
    sink.write(_entry())
    sink.write(_entry("crowdsec.get_metrics"))
    lines = p.read_text(encoding="utf-8").splitlines()
    expected_lines = 2
    assert len(lines) == expected_lines
    assert json.loads(lines[0])["capability"] == "crowdsec.ban_ip"
    assert json.loads(lines[1])["capability"] == "crowdsec.get_metrics"


def test_creates_parent_directory(tmp_path: Path):
    p = tmp_path / "nested" / "audit.jsonl"
    FileAuditSink(p).write(_entry())
    assert p.exists()


def test_only_tokens_no_real_value(tmp_path: Path):
    p = tmp_path / "audit.jsonl"
    FileAuditSink(p).write(_entry())
    assert "203.0.113" not in p.read_text(encoding="utf-8")  # aucune vraie IP
