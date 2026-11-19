"""Command-line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def install_startup() -> str:
    if os.name != "nt":
        return "Starting with Windows is only supported on Windows."
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    startup.mkdir(parents=True, exist_ok=True)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    script = startup / "Ray Assistant.cmd"
    script.write_text(f'@echo off\r\nstart "" "{exe}" "{ROOT / "pew.py"}"\r\n', encoding="utf-8")
    return f"Ray will now start when you sign in ({script})."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ray, your desktop voice assistant")
    parser.add_argument("command", nargs="*", help="run one command without the UI, e.g. play lofi music")
    parser.add_argument("--install-startup", action="store_true", help="start Ray when you sign in to Windows")
    args = parser.parse_args(argv)

    if args.install_startup:
        print(install_startup())
        return 0

    if args.command:
        from .commands import CommandEngine

        print(CommandEngine().handle(" ".join(args.command)).text)
        return 0

    from .ui import RayApp

    RayApp().run()
    return 0
