"""Mirrors the app source (bot/, web/, common/, config/, scripts/, requirements.txt)
into ha-addon/app/, which is what the Dockerfile actually COPYs into the container.

Why this exists: Home Assistant's Supervisor builds a repository add-on using that
add-on's own folder as the Docker build context — it can't COPY files from outside
ha-addon/ (i.e. from the repo root, where the app actually lives for local dev).
Rather than move the whole app under ha-addon/ and disrupt the existing local dev
layout, this script keeps repo-root as the single edited source of truth and
regenerates a mirror for the container build.

Run this (from the repo root or anywhere) before committing/pushing a new add-on
version:  python ha-addon/sync_app.py
"""

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADDON_DIR = Path(__file__).resolve().parent
DEST = ADDON_DIR / "app"

DIRS_TO_MIRROR = ["bot", "web", "common", "config", "scripts"]
FILES_TO_MIRROR = ["requirements.txt"]

IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc")


def main():
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)

    for name in DIRS_TO_MIRROR:
        shutil.copytree(REPO_ROOT / name, DEST / name, ignore=IGNORE)
        print(f"synced {name}/")

    for name in FILES_TO_MIRROR:
        shutil.copy2(REPO_ROOT / name, DEST / name)
        print(f"synced {name}")

    print(f"\nDone. {DEST} now mirrors the current app source.")
    print("Commit this along with your change before pushing a new add-on version.")


if __name__ == "__main__":
    main()
