from __future__ import annotations

import shutil
from pathlib import Path

from cli.core.cpm_pkg import resolve_current_packet_dir


def cmd_cpm_cache_clear(args) -> None:
    cpm_dir = Path(args.cpm_dir or ".cpm").resolve()
    packet_dir = resolve_current_packet_dir(cpm_dir, args.packet)
    if packet_dir is None:
        raise SystemExit(f"[cpm:cache] packet not found: {args.packet}")

    hist = packet_dir / ".history"
    if not hist.exists():
        print("[cpm:cache] no cache found (no .history)")
        return
    shutil.rmtree(hist, ignore_errors=True)
    print(f"[cpm:cache] cleared {hist.as_posix()}")
