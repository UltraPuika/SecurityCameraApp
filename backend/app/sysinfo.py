"""Host CPU/RAM readings from /proc (Linux). Returns None elsewhere."""

import asyncio
import contextlib
from pathlib import Path
from typing import Any


def _cpu_times() -> tuple[int, int] | None:
    try:
        parts = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    except OSError:
        return None
    values = [int(p) for p in parts]
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    return idle, sum(values)


async def snapshot() -> dict[str, Any] | None:
    first = _cpu_times()
    if first is None:
        return None
    await asyncio.sleep(0.25)
    second = _cpu_times()
    cpu = None
    if second is not None and second[1] > first[1]:
        cpu = round(100 * (1 - (second[0] - first[0]) / (second[1] - first[1])), 1)
    mem: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                mem[key] = int(rest.split()[0]) * 1024
    except OSError:
        pass
    load = None
    with contextlib.suppress(OSError):
        load = [float(x) for x in Path("/proc/loadavg").read_text().split()[:3]]
    total, avail = mem.get("MemTotal"), mem.get("MemAvailable")
    return {
        "cpu_percent": cpu,
        "mem_total": total,
        "mem_used": total - avail if total is not None and avail is not None else None,
        "load": load,
    }
