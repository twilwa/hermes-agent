from types import SimpleNamespace

from hermes_cli.status import show_status


def test_show_status_includes_tavily_key(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-1234567890abcdef")

    show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    assert "Tavily" in output
    assert "tvly...cdef" in output


def test_show_status_reports_livekit_configured(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LIVEKIT_URL", "wss://livekit.example")
    monkeypatch.setenv("LIVEKIT_API_KEY", "lk-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "lk-secret")

    show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    livekit_line = next(line for line in output.splitlines() if "LiveKit" in line)
    assert "configured" in livekit_line
    assert "partially configured" not in livekit_line


def test_show_status_reports_livekit_partial_configuration(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("LIVEKIT_URL", "wss://livekit.example")
    monkeypatch.setenv("LIVEKIT_API_KEY", "lk-key")

    show_status(SimpleNamespace(all=False, deep=False))

    output = capsys.readouterr().out
    livekit_line = next(line for line in output.splitlines() if "LiveKit" in line)
    assert "partially configured" in livekit_line
