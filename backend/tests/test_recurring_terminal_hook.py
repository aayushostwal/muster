import io
import json
import sys

import pytest

from app.services.recurring_terminal_hook import main


@pytest.mark.parametrize("event", ["Stop", "StopFailure", "agent-turn-complete"])
def test_completion_hook_writes_summary_atomically(tmp_path, monkeypatch, event):
    path = tmp_path / "complete.json"
    monkeypatch.setenv("MUSTER_TURN_COMPLETE_FILE", str(path))
    payload = {"hook_event_name": event, "last_assistant_message": "Finished"}
    monkeypatch.setattr(sys, "argv", ["hook"])
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    main()
    assert json.loads(path.read_text()) == {"failed": event == "StopFailure", "message": "Finished"}
    assert not path.with_suffix(".tmp").exists()


@pytest.mark.parametrize("payload", [{"hook_event_name": "SubagentStop"}, {"hook_event_name": "Stop", "background_tasks": [{"id": "still-running"}]}, {"hook_event_name": "Stop", "session_crons": [{"id": "loop"}]}])
def test_hook_does_not_close_subagent_or_background_work(tmp_path, monkeypatch, payload):
    path = tmp_path / "complete.json"
    monkeypatch.setenv("MUSTER_TURN_COMPLETE_FILE", str(path))
    monkeypatch.setattr(sys, "argv", ["hook", json.dumps(payload)])
    main()
    assert not path.exists()
