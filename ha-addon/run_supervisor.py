#!/usr/bin/env python3
"""Minimal process supervisor for the add-on container: starts the bot and web
processes directly and watches both. Forwards SIGTERM/SIGINT (from `docker
stop` / Supervisor) to both children for a clean shutdown.

This exists in place of relying on the base image's s6-overlay service
supervision (the previous approach): that repeatedly failed with
"s6-overlay-suexec: fatal: can only run as pid 1" in ways that couldn't be
diagnosed or reproduced outside a real Home Assistant Supervisor. This script
has no dependency on s6-overlay conventions at all — it's just Python
subprocess management, which is easy to reason about and test.

If one child dies, only that child is restarted in place — a transient
failure in the bot (e.g. a DNS hiccup reaching api.telegram.org right after
boot) used to take the whole container down, killing the unrelated, still-
healthy web dashboard along with it. The container only gives up and exits
(for Docker/Supervisor to restart it fresh) once a single process has
crash-looped past MAX_RESTARTS within RESTART_WINDOW_SECONDS.
"""

import signal
import subprocess
import sys
import time

PROCESSES = [
    ("bot", ["python3", "scripts/run_bot.py"]),
    ("web", ["python3", "scripts/run_web.py"]),
]

MAX_RESTARTS = 5
RESTART_WINDOW_SECONDS = 60

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

    process_args = dict(PROCESSES)
    for name, args in PROCESSES:
        log(f"starting {name}: {' '.join(args)}")
        running.append((name, subprocess.Popen(args, cwd="/app")))

    restart_times: dict[str, list[float]] = {name: [] for name, _ in PROCESSES}

    while True:
        for i, (name, proc) in enumerate(running):
            code = proc.poll()
            if code is None:
                continue

            log(f"{name} exited with code {code}")
            now = time.time()
            recent = [t for t in restart_times[name] if now - t < RESTART_WINDOW_SECONDS]
            recent.append(now)
            restart_times[name] = recent

            if len(recent) > MAX_RESTARTS:
                log(
                    f"{name} crash-looped {len(recent)} times in {RESTART_WINDOW_SECONDS}s "
                    "— stopping the container so it can restart"
                )
                shutdown(1)

            log(f"restarting {name}")
            running[i] = (name, subprocess.Popen(process_args[name], cwd="/app"))
        time.sleep(2)


if __name__ == "__main__":
    main()
