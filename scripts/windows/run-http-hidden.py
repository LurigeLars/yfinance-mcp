from __future__ import annotations

import argparse
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_MAX_LOG_BYTES = 5 * 1024 * 1024


def _log_paths() -> tuple[Path, Path]:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    log_dir = base / "yfinance-mcp"
    return log_dir / "http.log", log_dir / "http.log.1"


def _rotate_log(log_file: Path, old_log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    if log_file.exists() and log_file.stat().st_size >= _MAX_LOG_BYTES:
        if old_log_file.exists():
            old_log_file.unlink()
        log_file.replace(old_log_file)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8772)
    args = parser.parse_args()

    if not 1 <= args.port <= 65535:
        raise SystemExit("port must be between 1 and 65535")

    os.environ["YFINANCE_MCP_HOST"] = "127.0.0.1"
    os.environ["YFINANCE_MCP_PORT"] = str(args.port)

    log_file, old_log_file = _log_paths()
    _rotate_log(log_file, old_log_file)

    with log_file.open("a", encoding="utf-8") as log:
        with redirect_stdout(log), redirect_stderr(log):
            from yfinance_mcp.http import main as run_http

            run_http()
    return 0


if __name__ == "__main__":
    sys.exit(main())
