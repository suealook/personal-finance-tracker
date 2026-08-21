#!/usr/bin/env python3
"""Minimal process supervisor for the add-on container: starts the bot and web
processes directly and waits on both. Forwards SIGTERM/SIGINT (from `docker
stop` / Supervisor) to both children for a clean shutdown; exits non-zero if
either child dies unexpectedly, so Docker/Supervisor can restart the container.

This exists in place of relying on the base image's s6-overlay service
supervision (the previous approach): that repeatedly failed with
"s6-overlay-suexec: fatal: can only run as pid 1" in ways that couldn't be
diagnosed or reproduced outside a real Home Assistant Supervisor. This script
has no dependency on s6-overlay conventions at all — it's just Python
subprocess management, which is easy to reason about and test.
"""

import signal
import subprocess
import sys
import time

PROCESSES = [
    ("bot", ["python3", "scripts/run_bot.py"]),
    ("web", ["python3", "scripts/run_web.py"]),
]

running = []


def log(msg: str):
    print(f"[supervisor] {msg}", flush=True)


def shutdown(exit_code: int = 0):
    log("stopping...")
    for name, proc in running:
        if proc.poll() is None:
            proc.terminate()
    deadline = time.time() + 10
    for name, proc in running:
        remaining = max(0, deadline - time.time())
        try:
            proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            log(f"{name} didn't exit in time, killing it")
            proc.kill()
    sys.exit(exit_code)


def on_signal(signum, _frame):
    log(f"received signal {signum}")
    shutdown(0)


def main():
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    for name, args in PROCESSES:
        log(f"starting {name}: {' '.join(args)}")
        running.append((name, subprocess.Popen(args, cwd="/app")))

    while True:
        for name, proc in running:
            code = proc.poll()
            if code is not None:
                log(f"{name} exited with code {code} — stopping the container so it can restart")
                shutdown(1)
        time.sleep(2)


if __name__ == "__main__":
    main()
