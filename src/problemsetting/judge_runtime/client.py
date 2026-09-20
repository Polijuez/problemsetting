#!/usr/bin/env python3
"""Client side of the pool REPL: send one command, stream its output back.

Run inside a pool container::

    podman exec -i <container> /env/bin/python3 /run/judge_runtime/client.py

The request travels to the launcher over the container's control FIFO, and the
reply arrives as the launcher mirrors the command's output to a spool file; this
process follows that file until the command's end marker appears, so the caller
sees output live instead of after the fact.

Reads a JSON request on stdin::

    {"id": "sub-1",
     "command": "submit demo CPP17 /problems/demo/solution.cpp -tl 2 -ml 262144",
     "timeout": 300}

writes the command's raw output to stdout, and exits with the command's status --
so ``podman exec``'s exit code is already the answer, with no second round trip.
``timeout`` (seconds, default 600) bounds a hung grading.
"""

from __future__ import annotations

import json
import os
import sys
import time

#: Must match the launcher's; see :mod:`problemsetting.judge_runtime.launcher`.
POOL_DIR = os.environ.get("JUDGE_POOL_DIR", "/run/dmoj-pool")
CONTROL_FIFO = f"{POOL_DIR}/ctl"
SPOOL_DIR = f"{POOL_DIR}/spool"
READY_MARKER = f"{POOL_DIR}/ready"

BEGIN_PREFIX = "<<<DMOJ-POOL BEGIN "
END_PREFIX = "<<<DMOJ-POOL END "

#: How long to wait for a (possibly cold) judge to finish discovery.  The
#: toolkit only drives containers it started itself, and a container started
#: moments ago is still self-testing every executor.
READY_TIMEOUT = 900.0
DEFAULT_TIMEOUT = 600.0

#: This client's own failures.  Above 100, so they cannot be confused with the
#: launcher's normalised command status (0 success, 1 failure).
FAILED_NOT_READY = 101
FAILED_TIMEOUT = 102
FAILED_NO_OUTPUT = 103


class Transcript:
    """One command's output, followed live from its spool file.

    The spool file *is* the transport: the launcher writes the command's output
    there and signs off with an end marker carrying the status, so following the
    file gives live output and the status without a second round trip.
    """

    def __init__(self, command_id: str, timeout: float) -> None:
        self.command_id = command_id
        self.path = os.path.join(SPOOL_DIR, f"{command_id}.out")
        self.timeout = timeout
        self._begin = f"{BEGIN_PREFIX}{command_id}>>>"
        self._end = f"{END_PREFIX}{command_id} rc="
        #: The command's status, or None while it is still running.
        self.status: int | None = None

    def lines(self):
        """Yield the command's output lines, excluding the framing markers."""
        deadline = time.monotonic() + self.timeout
        started = False

        while True:
            try:
                handle = open(self.path, encoding="utf-8", errors="replace")
            except FileNotFoundError:
                if time.monotonic() >= deadline:
                    return
                time.sleep(0.05)
                continue

            with handle:
                while True:
                    line = handle.readline()
                    if not line:  # caught up; the file may still grow
                        if time.monotonic() >= deadline:
                            return
                        time.sleep(0.05)
                        continue
                    stripped = line.rstrip("\n")
                    if not started:
                        started = stripped == self._begin
                        continue
                    if stripped.startswith(self._end):
                        self.status = int(stripped[len(self._end) : -3])
                        return
                    if stripped:
                        yield stripped

    @property
    def timed_out(self) -> bool:
        return self.status is None


def wait_ready(timeout: float) -> bool:
    """Block until the launcher has finished discovery; False on timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(READY_MARKER):
            return True
        time.sleep(0.1)
    return False


def send(command_id: str, command: str) -> None:
    """Hand one command to the launcher.

    ``O_WRONLY`` on a FIFO blocks until a reader is attached -- the launcher's
    reader is always attached -- which doubles as a synchronisation point: by the
    time this returns, the launcher has the command.
    """
    with open(CONTROL_FIFO, "w") as fifo:
        fifo.write(f"{command_id} :: {command}\n")
        fifo.flush()


def main() -> int:
    request = json.loads(sys.stdin.read() or "{}")
    command_id = str(request["id"])
    command = str(request["command"])
    timeout = float(request.get("timeout", DEFAULT_TIMEOUT))

    if not wait_ready(READY_TIMEOUT):
        print("error: judge container did not become ready", file=sys.stderr)
        return FAILED_NOT_READY

    send(command_id, command)
    transcript = Transcript(command_id, timeout)
    for line in transcript.lines():
        print(line, flush=True)

    if transcript.timed_out:
        print(f"error: command timed out after {timeout:g}s", file=sys.stderr)
        return FAILED_TIMEOUT
    if transcript.status is None:  # pragma: no cover - defensive
        print("error: no output was produced for the command", file=sys.stderr)
        return FAILED_NO_OUTPUT
    return transcript.status


if __name__ == "__main__":
    sys.exit(main())
