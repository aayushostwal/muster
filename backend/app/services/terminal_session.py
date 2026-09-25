"""Small POSIX PTY wrapper used by the interactive task runtime.

The browser never receives a shell. It is attached only to an argv assembled
by an agent backend adapter (Codex or Claude Code).
"""
from __future__ import annotations

import asyncio
import errno
import fcntl
import os
import pty
import signal
import struct
import termios
from collections.abc import Awaitable, Callable


OutputCallback = Callable[[bytes], Awaitable[None]]
ExitCallback = Callable[[int], Awaitable[None]]


class TerminalSession:
    def __init__(
        self,
        argv: list[str],
        *,
        cwd: str,
        env: dict[str, str],
        cols: int = 120,
        rows: int = 32,
        on_output: OutputCallback,
        on_exit: ExitCallback,
    ) -> None:
        self.argv = argv
        self.cwd = cwd
        self.env = env
        self.cols = cols
        self.rows = rows
        self.on_output = on_output
        self.on_exit = on_exit
        self.process: asyncio.subprocess.Process | None = None
        self.master_fd: int | None = None
        self._output_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._pump_task: asyncio.Task | None = None
        self._wait_task: asyncio.Task | None = None
        self._closed = False

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process is not None else None

    @property
    def returncode(self) -> int | None:
        return self.process.returncode if self.process is not None else None

    async def start(self) -> None:
        if os.name != "posix":
            raise OSError("Interactive terminals currently require macOS or Linux")
        if self.process is not None:
            return

        master_fd, slave_fd = pty.openpty()
        self.master_fd = master_fd
        self._set_size(slave_fd, self.cols, self.rows)
        os.set_blocking(master_fd, False)
        runtime_env = {
            **self.env,
            "TERM": self.env.get("TERM", "xterm-256color"),
            "COLORTERM": self.env.get("COLORTERM", "truecolor"),
        }
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.argv,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=self.cwd,
                env=runtime_env,
                start_new_session=True,
            )
        except BaseException:
            os.close(master_fd)
            self.master_fd = None
            raise
        finally:
            os.close(slave_fd)

        loop = asyncio.get_running_loop()
        loop.add_reader(master_fd, self._read_ready)
        self._pump_task = asyncio.create_task(self._pump_output())
        self._wait_task = asyncio.create_task(self._wait_for_exit())

    def _read_ready(self) -> None:
        fd = self.master_fd
        if fd is None:
            return
        try:
            data = os.read(fd, 64 * 1024)
        except BlockingIOError:
            return
        except OSError as exc:
            if exc.errno not in {errno.EIO, errno.EBADF}:
                self._output_queue.put_nowait(
                    f"\r\n[muster terminal read error: {exc}]\r\n".encode()
                )
            self._stop_reader()
            self._output_queue.put_nowait(None)
            return
        if not data:
            self._stop_reader()
            self._output_queue.put_nowait(None)
            return
        self._output_queue.put_nowait(data)

    async def _pump_output(self) -> None:
        while True:
            data = await self._output_queue.get()
            if data is None:
                return
            await self.on_output(data)

    async def _wait_for_exit(self) -> None:
        assert self.process is not None
        exit_code = await self.process.wait()
        self._stop_reader()
        self._output_queue.put_nowait(None)
        if self._pump_task is not None:
            await self._pump_task
        await self.on_exit(exit_code)
        self.close_fd()

    async def write(self, data: bytes) -> None:
        if not data or self.master_fd is None or self.returncode is not None:
            return
        view = memoryview(data)
        while view:
            try:
                written = os.write(self.master_fd, view)
                view = view[written:]
            except BlockingIOError:
                await asyncio.sleep(0)
            except OSError as exc:
                if exc.errno not in {errno.EIO, errno.EBADF}:
                    raise
                return

    async def resize(self, cols: int, rows: int) -> None:
        if self.master_fd is None or self.returncode is not None:
            return
        self.cols = cols
        self.rows = rows
        self._set_size(self.master_fd, cols, rows)
        if self.pid is not None:
            try:
                os.killpg(self.pid, signal.SIGWINCH)
            except ProcessLookupError:
                pass

    async def terminate(self, grace_seconds: float = 5.0) -> None:
        if self.process is None or self.process.returncode is not None:
            return
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(self.process.wait(), timeout=grace_seconds)
        except asyncio.TimeoutError:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await self.process.wait()

    async def wait(self) -> int | None:
        if self._wait_task is not None:
            await self._wait_task
        return self.returncode

    def _stop_reader(self) -> None:
        if self.master_fd is None:
            return
        try:
            asyncio.get_running_loop().remove_reader(self.master_fd)
        except (RuntimeError, ValueError):
            pass

    def close_fd(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._stop_reader()
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

    @staticmethod
    def _set_size(fd: int, cols: int, rows: int) -> None:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
