import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.services import terminal_history as history
from app.api.routes import tasks


def write(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(''.join(json.dumps(e) + '\n' for e in events))
    return path


def codex(kind, **kwargs):
    return {'type': 'response_item', 'timestamp': '2026-10-01', 'payload': {'type': kind, **kwargs}}


def test_native_formats_hide_internal_reasoning_and_instructions(tmp_path):
    events = [
        codex('message', role='developer', content=[{'text': 'private instructions'}]),
        codex('message', role='user', content=[{'text': 'Original prompt'}, None, {'other': 1}]),
        codex('message', role='assistant', content=[{'text': 'PR raised'}]),
        codex('function_call', name='exec', arguments='pytest'),
        codex('custom_tool_call', name='edit', input={'file': 'app.py'}),
        codex('function_call_output', output='passed'),
        codex('custom_tool_call_output', output={'result': 'done'}),
        codex('reasoning', encrypted_content='hidden'),
        {'type': 'user', 'message': {'content': 'Follow up'}},
        {'type': 'assistant', 'message': {'content': [None, {'type': 'text', 'text': 'Done'}, {'type': 'tool_use', 'name': 'Edit', 'input': {}}, {'type': 'tool_result', 'content': 'OK'}, {'type': 'thinking', 'thinking': 'hidden'}]}},
        {'type': 'response_item', 'payload': None}, {'type': 'other'},
        codex('message', role='assistant', content=[]),
        codex('message', role='assistant', content=[{'text': 'x' * 70000}]), [],
    ]
    page = history.read_page([write(tmp_path / 'native.jsonl', events)])
    assert page['next_cursor'] is None
    assert [i['role'] for i in page['items'][:6]] == ['user', 'assistant', 'tool', 'tool', 'tool_result', 'tool_result']
    assert page['items'][0]['text'] == 'Original prompt'
    assert page['items'][-1]['truncated'] and len(page['items'][-1]['text']) == 65536
    assert 'hidden' not in str(page) and 'private instructions' not in str(page)


def test_pages_recover_from_bad_records_and_read_older_output(tmp_path, monkeypatch):
    monkeypatch.setattr(history, '_PAGE_ITEMS', 2)
    first = write(tmp_path / 'one.jsonl', [codex('message', role='user', content=[{'text': 'Beginning'}])])
    with first.open('ab') as stream:
        stream.write(b'invalid\n\xff\n')
    second = write(tmp_path / 'two.jsonl', [codex('message', role='assistant', content=[{'text': 'End'}]), codex('function_call_output', output='Result')])
    page = history.read_page([first, second])
    assert [i['text'] for i in page['items']] == ['Beginning', 'End']
    following = history.read_page([first, second], page['next_cursor'])
    assert following['items'][0]['text'] == 'Result' and following['next_cursor'] is None
    assert history.read_page([]) == {'items': [], 'next_cursor': None}
    with first.open('ab') as stream:
        stream.write(b'{"partial":')
    assert history.read_page([first])['next_cursor'] is None
    monkeypatch.setattr(history, '_SCAN_BYTES', 1)
    assert history.read_page([second])['next_cursor'] is not None
    for cursor in ['bad', '-1:0', '0:-1', '4:0', '0:999999']:
        with pytest.raises(ValueError, match='Invalid history cursor'):
            history.read_page([first], cursor)


def test_paths_are_scoped_to_task_and_saved_native_handles(tmp_path, monkeypatch):
    task_id, other_id = uuid.uuid4(), uuid.uuid4()
    own, legacy = str(uuid.uuid4()), str(uuid.uuid4())
    monkeypatch.setattr(history, 'settings', SimpleNamespace(backend_sessions_dir=tmp_path / 'backend-sessions'))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex'))
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    a = write(tmp_path / f'backend-sessions/{task_id}/codex/sessions/{own}.jsonl', [])
    write(tmp_path / f'backend-sessions/{other_id}/codex/sessions/unrelated.jsonl', [])
    b = write(tmp_path / f'codex/sessions/rollout-{legacy}.jsonl', [])
    c = write(tmp_path / f'.claude/projects/project/{own}.jsonl', [])
    write(tmp_path / 'codex/sessions/unrelated.jsonl', [])
    assert set(history.history_paths(task_id, [own, legacy, '../../*'])) == {a, b, c}


@pytest.mark.asyncio
async def test_history_endpoint_uses_persisted_sessions_and_handles_errors(monkeypatch):
    task_id = uuid.uuid4()
    monkeypatch.setattr(tasks, '_get_task_or_404', AsyncMock(return_value=SimpleNamespace(session_id='native')))
    db = SimpleNamespace(execute=AsyncMock(return_value=Mock(scalars=Mock(return_value=Mock(all=Mock(return_value=['previous']))))))
    paths = Mock(return_value=[])
    monkeypatch.setattr(history, 'history_paths', paths)
    assert await tasks.terminal_history(task_id, '0:0', db) == {'items': [], 'next_cursor': None}
    paths.assert_called_once_with(task_id, ['previous', 'native'])
    with pytest.raises(HTTPException) as error:
        await tasks.terminal_history(task_id, 'bad', db)
    assert error.value.status_code == 400
    paths.side_effect = OSError('gone')
    with pytest.raises(HTTPException) as error:
        await tasks.terminal_history(task_id, '0:0', db)
    assert error.value.status_code == 503
    paths.side_effect = None
    monkeypatch.setattr(tasks, '_get_task_or_404', AsyncMock(return_value=SimpleNamespace(session_id=None)))
    assert await tasks.terminal_history(task_id, '0:0', db)


def test_legacy_shared_sessions_do_not_expose_other_tasks(tmp_path, monkeypatch):
    task_id, native = uuid.uuid4(), str(uuid.uuid4())
    monkeypatch.setattr(history, "settings", SimpleNamespace(backend_sessions_dir=tmp_path / "backend-sessions"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    shared = tmp_path / "codex/sessions"
    own = write(shared / f"rollout-{native}.jsonl", [{"timestamp": "2026-09-01"}])
    write(shared / "unrelated.jsonl", [])
    root = tmp_path / f"backend-sessions/{task_id}/codex"
    root.mkdir(parents=True)
    (root / "sessions").symlink_to(shared)
    assert history.history_paths(task_id, [native]) == [own]


def test_history_files_use_start_time_not_last_modified_time(tmp_path, monkeypatch):
    task_id = uuid.uuid4()
    monkeypatch.setattr(history, "settings", SimpleNamespace(backend_sessions_dir=tmp_path))
    root = tmp_path / str(task_id) / "codex/sessions"
    older = write(root / "b.jsonl", [{"timestamp": "2026-09-01"}])
    newer = write(root / "a.jsonl", [{"timestamp": "2026-10-01"}])
    bad = root / "bad.jsonl"
    bad.write_text("bad")
    array = write(root / "array.jsonl", [[]])
    assert history.history_paths(task_id, []) == [array, bad, older, newer]
