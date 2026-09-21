#!/usr/bin/env python3
"""Long-lived DMOJ judge inside a pool container: discovery once, then commands.

``dmoj-cli`` (``dmoj/cli.py``) builds a ``LocalJudge``, calls
``judge.listen()`` -- which is where problem discovery and the executor
self-test happen -- and then either runs one command and exits, or reads a REPL
from stdin.  Holding that process open is what makes a *pool* of judges worth
anything: the second submission into the same container pays neither the
self-test nor the problem scan again.

Three things ``dmoj-cli`` does not give us are added here, all by composing the
same DMOJ classes rather than reimplementing judge behaviour:

* **a control endpoint.**  ``dmoj/control.py`` exposes ``/update/problems``, but
  ``judge.py:main()`` only starts the ``HTTPServer`` on the *production*
  (``judge run``) path -- ``judgeenv.load_env(cli=True)`` never sets
  ``api_listen``.  After regenerating cases the pool has to re-scan problem
  directories without restarting containers (decision Q28), so the endpoint is
  started here, with ``dmoj.control.JudgeControlRequestHandler`` unchanged.

* **command framing.**  Commands arrive on a FIFO instead of stdin, because
  ``podman exec`` starts a *new* process: it cannot write to the stdin of the
  container's PID 1.  Every command's output is wrapped in
  ``<<<DMOJ-POOL BEGIN <id>>>>`` / ``<<<DMOJ-POOL END <id> rc=<n>>>>`` and
  mirrored to ``/run/dmoj-pool/spool/<id>.out`` so that
  :mod:`problemsetting.judge_runtime.client` can stream exactly one command's
  output back to the toolkit, no matter what else the container is printing.

* **per-case points.**  DMOJ's transcript reports a case's verdict, its time and
  its memory but never what the grader awarded it (``dmoj/judge.py:216``
  ``_ipc_result``): a checker that returns ``CheckerResult(True, 0.7 * point_value)``
  is indistinguishable, on the wire, from one that returns full marks.  The
  value is in-process the whole time -- ``Result.points`` holds what was
  awarded and ``Result.total_points`` what the case was worth
  (``dmoj/result.py:48,77``) -- and ``test_case_status_packet(position, result)``
  is handed the whole ``Result`` right after that line is printed
  (``dmoj/judge.py:236-237``).  ``LocalPacketManager`` makes that method a no-op,
  so the pool replaces it with one that prints :data:`CASE_POINTS_FMT` beside
  the case it describes; :mod:`problemsetting.judges` reads the pair.

The process exits -- stopping the container -- after ``JUDGE_IDLE_TIMEOUT``
seconds with no command (idle autostop, decision Q28).
"""

from __future__ import annotations

import os
import re
import select
import shlex
import sys
import threading
import time
from http.server import HTTPServer

#: Where the control FIFO, its spool directory, and the ready marker live.
#: Overridable because the image's ``/run`` is root-owned while the judge runs
#: as ``judge``: the container's command creates and chowns the directory before
#: dropping privileges (see :mod:`problemsetting.judges`).
POOL_DIR = os.environ.get("JUDGE_POOL_DIR", "/run/dmoj-pool")
CONTROL_FIFO = f"{POOL_DIR}/ctl"
SPOOL_DIR = f"{POOL_DIR}/spool"
IDLE_TIMEOUT = float(os.environ.get("JUDGE_IDLE_TIMEOUT", "900"))

CONFIG_PATH = os.environ.get("JUDGE_CONFIG", "/judge.yml")

#: The DMOJ control API (``dmoj/control.py``) is bound to the container's own
#: loopback: nothing outside the container needs it, and the toolkit reaches it
#: through ``podman exec``.
API_HOST = "127.0.0.1"
API_PORT = int(os.environ.get("JUDGE_API_PORT", "9998"))

#: Framing around one command's output.  The launcher writes it; the client (in
#: :mod:`problemsetting.judge_runtime.client`) recognises it.  Nothing else in
#: the transcript is trustworthy -- a submission's own output can contain any
#: text -- so the client keys off these two lines and nothing else.
MARKER_FMT = "<<<DMOJ-POOL {kind} {command_id}>>>"
END_MARKER_FMT = "<<<DMOJ-POOL END {command_id} rc={status}>>>"

#: One synthetic line per graded case, carrying the two numbers DMOJ never
#: prints: the points the grader awarded, and what the case was worth.  It is
#: emitted immediately after the case's own ``Test case`` line, so the two are
#: read together in the order the judge reported them.  The numbers are
#: ``repr``-ed -- ``0.7`` stays ``0.7`` -- so a fractional score survives the
#: transcript exactly, and the line still belongs to the pool's own vocabulary
#: (``<<<DMOJ-POOL ...>>>``) rather than looking like judge output.
CASE_POINTS_FMT = "<<<DMOJ-POOL CASE {position} {points!r}/{total!r}>>>"


def case_points_line(position: int, points: float, total: float) -> str:
    """The transcript line for one case's points.

    A plain function so the format is readable and testable without a judge
    (nothing here imports ``dmoj``, which only exists inside the container).
    """
    return CASE_POINTS_FMT.format(position=position, points=points, total=total)


def _test_case_status_packet(position, result) -> None:
    """``LocalPacketManager.test_case_status_packet`` with the points kept.

    Installed on the judge's own packet manager (:func:`_install`).  DMOJ calls
    it with the whole ``Result`` for every graded case and ignores it, so this
    is where the two numbers the transcript drops are still available.
    """
    print(case_points_line(position, result.points, result.total_points), flush=True)


#: DMOJ's own commands are written as ``execute(...) -> Optional[int]`` and in
#: practice all return ``None`` on success (``dmoj/commands/submit.py:execute``
#: ends after ``begin_grading``), so a status cannot just be forwarded: it is
#: normalised to this package's convention, 0 for success and 1 for anything
#: else.  A grading failure is not a command failure -- it is reported as
#: verdicts, and :func:`problemsetting.judges.parse_grading` reads those.
STATUS_BY_COMMAND = {None: 0, 0: 0}

#: The toolkit tags each command with its own id, ``<id> :: <command>``, so the
#: two sides agree on the spool filename without the launcher having to hand one
#: back.  Untagged lines still work; they get a sequence number instead.
COMMAND_RE = re.compile(r"([A-Za-z0-9_.:-]+)\s+::\s+(.*)\Z", re.DOTALL)


def _mark_ready() -> None:
    """Record that discovery finished, so ``judges status`` can tell."""
    try:
        with open(f"{POOL_DIR}/ready", "w") as handle:
            handle.write(f"{os.getpid()}\n")
    except OSError:
        pass


class _Tee:
    """A stdout that writes to the container log *and* to the current spool file.

    Everything the judge reports -- ``Unexpected error``, ``Test case  1 WA
    [...]``, the compile-error log, the ``problems`` listing -- goes through
    ``print``, so one redirected ``sys.stdout`` captures it all without the
    judge knowing anything about the pool.
    """

    def __init__(self, stream) -> None:
        self._stream = stream
        self._spool = None
        self._lock = threading.Lock()

    def begin(self, spool) -> None:
        with self._lock:
            self._spool = spool

    def finish(self) -> None:
        with self._lock:
            spool, self._spool = self._spool, None
        if spool is not None:
            spool.close()

    def write(self, text: str) -> int:
        with self._lock:
            spool = self._spool
        try:
            written = self._stream.write(text)
        except ValueError:  # stdout already closed
            written = len(text)
        if spool is not None:
            try:
                spool.write(text)
            except ValueError:
                pass
        return written

    def flush(self) -> None:
        with self._lock:
            spool = self._spool
        for stream in (self._stream, spool):
            if stream is not None:
                try:
                    stream.flush()
                except ValueError:
                    pass

    def isatty(self) -> bool:
        return False


TEE = _Tee(sys.stdout)


def _install() -> None:
    """Import and wire the judge.  Runs once; ``listen()`` is the slow part."""
    from dmoj import contrib, executors, judgeenv
    from dmoj.cli import LocalJudge
    from dmoj.commands import all_commands, commands, register_command
    from dmoj.control import JudgeControlRequestHandler
    from dmoj.error import InvalidCommandException

    sys.argv = ["dmoj-pool", "-c", CONFIG_PATH, "--no-ansi"]
    judgeenv.load_env(cli=True)
    executors.load_executors()
    contrib.load_contrib_modules()

    judge = LocalJudge()
    # `LocalPacketManager.test_case_status_packet` is a no-op, and it is the one
    # hook handed the whole `Result` -- points included -- right after the case
    # line is printed (`dmoj/judge.py:236-237`).  Replacing the bound method on
    # the judge's own instance keeps every other packet method, and the judge's
    # behaviour, exactly DMOJ's; only this one observation is added.
    judge.packet_manager.test_case_status_packet = _test_case_status_packet
    for command in all_commands:
        register_command(command(judge))

    class Handler(JudgeControlRequestHandler):
        # `Judge` needs no packet manager here: LocalPacketManager's
        # supported_problems_packet is a no-op, and problem_count is what
        # /metrics would report.
        pass

    Handler.judge = judge
    server = HTTPServer((API_HOST, API_PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def run_command(line: str) -> int:
        if not line:
            return 127
        if line[0] in commands:
            try:
                return commands[line[0]].execute(line[1:])
            except InvalidCommandException as error:
                if error.message:
                    print(f"error: {error.message}", flush=True)
                return 1
        print(f"Unrecognized command {line[0]}", flush=True)
        return 127

    return judge, run_command, server


def _reader(fifo_fd: int, queue: list[tuple[str, str]], stop: threading.Event) -> None:
    """Read newline-terminated commands off the FIFO into ``queue``."""
    buffer = b""
    while not stop.is_set():
        try:
            ready, _, _ = select.select([fifo_fd], [], [], 1.0)
        except InterruptedError:
            continue
        if not ready:
            continue
        chunk = os.read(fifo_fd, 65536)
        if not chunk:  # every writer closed; wait for the next one
            continue
        buffer += chunk
        while b"\n" in buffer:
            raw, buffer = buffer.split(b"\n", 1)
            queue.append((raw.decode("utf-8", "replace"), ""))


def main() -> int:
    os.makedirs(SPOOL_DIR, exist_ok=True)
    for stale in os.listdir(SPOOL_DIR):
        try:
            os.unlink(os.path.join(SPOOL_DIR, stale))
        except OSError:
            pass
    if os.path.exists(CONTROL_FIFO):
        os.unlink(CONTROL_FIFO)
    os.mkfifo(CONTROL_FIFO, 0o666)

    # Opening the FIFO O_RDWR keeps a writer end alive, so the reader never sees
    # EOF and the judge never has to be reopened between invocations.
    fifo_fd = os.open(CONTROL_FIFO, os.O_RDWR)

    queue: list[tuple[str, str]] = []
    stop = threading.Event()
    threading.Thread(target=_reader, args=(fifo_fd, queue, stop), daemon=True).start()

    judge, run_command, server = _install()
    # `sys.stdout` stays the tee for the process's whole life: the judge answers
    # every command with `print`, so nothing may be restored once the pool is up
    # (restoring it after `listen()` silently discards every verdict).
    sys.stdout = TEE
    judge.listen()
    print("dmoj-pool: ready", flush=True)
    _mark_ready()

    sequence = 0
    last = time.monotonic()
    try:
        while True:
            if not queue:
                if time.monotonic() - last > IDLE_TIMEOUT:
                    print(f"dmoj-pool: idle for {IDLE_TIMEOUT:g}s, stopping", flush=True)
                    break
                time.sleep(0.05)
                continue
            raw, _ = queue.pop(0)
            last = time.monotonic()
            match = COMMAND_RE.match(raw)
            if match:
                command_id, line = match.group(1), match.group(2)
            else:
                sequence += 1
                command_id, line = str(sequence), raw

            spool_path = os.path.join(SPOOL_DIR, f"{command_id}.out")
            with open(spool_path, "w", encoding="utf-8") as spool:
                TEE.begin(spool)
                print(MARKER_FMT.format(kind="BEGIN", command_id=command_id), flush=True)
                try:
                    status = run_command(shlex.split(line))
                except KeyboardInterrupt:
                    status = 1
                except Exception as error:  # a broken command must not kill the pool
                    print(f"error: {error!r}", flush=True)
                    status = 1
                print(
                    END_MARKER_FMT.format(
                        command_id=command_id, status=STATUS_BY_COMMAND.get(status, 1)
                    ),
                    flush=True,
                )
                TEE.finish()
    finally:
        stop.set()
        judge.murder()
        server.shutdown()
        os.close(fifo_fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
