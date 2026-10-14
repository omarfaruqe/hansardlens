from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

FIXTURE = Path(__file__).parent / "fixtures" / "mini_hansard.xml"


def test_inspect_local_file_writes_report(tmp_path, settings, capsys):
    settings.DATA_DIR = tmp_path
    call_command("inspect_sitting", file=str(FIXTURE))

    report = tmp_path / "reports" / "structure_mini_hansard.xml.txt"
    assert report.exists()
    assert "/Hansard/Sitting/Intervention" in report.read_text()
    assert "Report written" in capsys.readouterr().out


def test_inspect_download_uses_built_url(tmp_path, settings, monkeypatch):
    settings.DATA_DIR = tmp_path
    seen = []

    def fake_fetch(url, user_agent, timeout=60):
        seen.append(url)
        return FIXTURE.read_bytes()

    monkeypatch.setattr("debates.management.commands.inspect_sitting.fetch", fake_fetch)
    call_command("inspect_sitting", parliament=44, session=1, sitting=7, lang="both")

    assert seen == [
        "https://www.ourcommons.ca/Content/House/441/Debates/007/HAN007-E.XML",
        "https://www.ourcommons.ca/Content/House/441/Debates/007/HAN007-F.XML",
    ]
    assert (tmp_path / "raw" / "P44S1-007-en.xml").exists()
    assert (tmp_path / "raw" / "P44S1-007-fr.xml").exists()


def test_inspect_html_error_page_raises(tmp_path, settings):
    settings.DATA_DIR = tmp_path
    bad = tmp_path / "bad.xml"
    bad.write_text("<html><body>Not found</body>")
    with pytest.raises(CommandError):
        call_command("inspect_sitting", file=str(bad))


def test_missing_file_raises(tmp_path, settings):
    settings.DATA_DIR = tmp_path
    with pytest.raises(CommandError):
        call_command("inspect_sitting", file=str(tmp_path / "nope.xml"))
