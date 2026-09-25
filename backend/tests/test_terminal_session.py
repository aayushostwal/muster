from __future__ import annotations

import asyncio
import os
import sys

import pytest

from app.services.terminal_session import TerminalSession


pytestmark = pytest.mark.skipif(os.name != "posix", reason="PTY runtime is POSIX-only")


@pytest.mark.asyncio
async def test_terminal_session_streams_input_output_and_exit(tmp_path):
    output = bytearray()
    exited = asyncio.Event()
    exit_codes: list[int] = []

    async def on_output(data: bytes) -> None:
        output.extend(data)

    async def on_exit(exit_code: int) -> None:
        exit_codes.append(exit_code)
        exited.set()

    session = TerminalSession(
        ["/bin/sh", "-c", "printf 'ready\\n'; IFS= read -r line; printf 'got:%s\\n' \"$line\""],
        cwd=str(tmp_path),
        env=dict(os.environ),
        cols=80,
        rows=24,
        on_output=on_output,
        on_exit=on_exit,
    )

    await session.start()
    for _ in range(100):
        if b"ready" in output:
            break
        await asyncio.sleep(0.01)
    await session.resize(100, 30)
    await session.write(b"hello terminal\n")
    await asyncio.wait_for(exited.wait(), timeout=5)

    assert exit_codes == [0]
    assert b"ready" in output
    assert b"got:hello terminal" in output
    assert session.returncode == 0


@pytest.mark.asyncio
async def test_terminal_session_terminate_stops_process_group(tmp_path):
    exited = asyncio.Event()

    async def on_output(_data: bytes) -> None:
        return None

    async def on_exit(_exit_code: int) -> None:
        exited.set()

    session = TerminalSession(
        ["/bin/sh", "-c", "sleep 30 & wait"],
        cwd=str(tmp_path),
        env=dict(os.environ),
        on_output=on_output,
        on_exit=on_exit,
    )
    await session.start()
    await session.terminate(grace_seconds=0.2)
    await asyncio.wait_for(exited.wait(), timeout=5)

    assert session.returncode is not None


@pytest.mark.asyncio
async def test_terminal_session_drains_output_after_fast_process_exit(tmp_path):
    output = bytearray()
    exited = asyncio.Event()

    async def on_output(data: bytes) -> None:
        output.extend(data)

    async def on_exit(_exit_code: int) -> None:
        exited.set()

    expected_size = 512 * 1024
    session = TerminalSession(
        [sys.executable, "-c", f"import os; os.write(1, b'x' * {expected_size})"],
        cwd=str(tmp_path),
        env=dict(os.environ),
        on_output=on_output,
        on_exit=on_exit,
    )

    await session.start()
    await asyncio.wait_for(exited.wait(), timeout=5)

    assert len(output) == expected_size
    assert output == b"x" * expected_size


@pytest.mark.asyncio
async def test_terminal_session_child_owns_the_controlling_tty(tmp_path):
    output = bytearray()
    exited = asyncio.Event()

    async def on_output(data: bytes) -> None:
        output.extend(data)

    async def on_exit(_exit_code: int) -> None:
        exited.set()

    session = TerminalSession(
        [
            sys.executable,
            "-c",
            "import os; print(f'{os.tcgetpgrp(0)}:{os.getpgrp()}', flush=True)",
        ],
        cwd=str(tmp_path),
        env=dict(os.environ),
        on_output=on_output,
        on_exit=on_exit,
    )

    await session.start()
    await asyncio.wait_for(exited.wait(), timeout=5)

    foreground, process_group = output.decode().strip().split(":")
    assert foreground == process_group


@pytest.mark.asyncio
async def test_terminal_session_ctrl_c_reaches_foreground_process(tmp_path):
    output = bytearray()
    exited = asyncio.Event()

    async def on_output(data: bytes) -> None:
        output.extend(data)

    async def on_exit(_exit_code: int) -> None:
        exited.set()

    program = (
        "import signal, time; "
        "signal.signal(signal.SIGINT, lambda *_: (print('interrupted', flush=True), exit(0))); "
        "print('ready', flush=True); time.sleep(30)"
    )
    session = TerminalSession(
        [sys.executable, "-c", program],
        cwd=str(tmp_path),
        env=dict(os.environ),
        on_output=on_output,
        on_exit=on_exit,
    )

    await session.start()
    for _ in range(100):
        if b"ready" in output:
            break
        await asyncio.sleep(0.01)
    await session.write(b"\x03")
    await asyncio.wait_for(exited.wait(), timeout=5)

    assert b"interrupted" in output
