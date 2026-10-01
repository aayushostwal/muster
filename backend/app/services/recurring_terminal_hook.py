"""Native CLI hook: record a recurring turn's completion for its owner."""
import json
import os
from pathlib import Path
import sys


def main() -> None:
    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else json.load(sys.stdin)
    event = payload.get("hook_event_name") or payload.get("type")
    if event not in {"Stop", "StopFailure", "agent-turn-complete"}:
        return
    if payload.get("background_tasks") or payload.get("session_crons"):
        return
    path = Path(os.environ["MUSTER_TURN_COMPLETE_FILE"])
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "failed": event == "StopFailure",
        "message": payload.get("last_assistant_message") or payload.get("last-assistant-message") or "",
    }), encoding="utf-8")
    temporary.replace(path)


if __name__ == "__main__":
    main()
