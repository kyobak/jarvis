#!/usr/bin/env python3
"""Sample CPU and memory of the running Jarvis stack (Python server + WebKit UI).

    python3 scripts/measure_cpu.py --seconds 60

Run it while the app sits idle to check the Phase 1 target (idle UI <= 10% CPU).
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import time

GROUPS = {
    "server (python)": ("jarvis", "python"),
    "UI (WebKit)": ("com.apple.WebKit", "WebContent", "WebKit.GPU"),
}


def sample() -> dict[str, tuple[float, float]]:
    out = subprocess.run(["ps", "-A", "-o", "%cpu=,rss=,command="], capture_output=True, text=True).stdout
    totals = {g: [0.0, 0.0] for g in GROUPS}
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        cpu, rss, cmd = float(parts[0]), float(parts[1]), parts[2]
        for group, needles in GROUPS.items():
            if any(n in cmd for n in needles) and "measure_cpu" not in cmd:
                totals[group][0] += cpu
                totals[group][1] += rss / 1024
                break
    return {g: (c, m) for g, (c, m) in totals.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--interval", type=float, default=2.0)
    args = ap.parse_args()

    series: dict[str, list[tuple[float, float]]] = {g: [] for g in GROUPS}
    end = time.time() + args.seconds
    while time.time() < end:
        for g, v in sample().items():
            series[g].append(v)
        time.sleep(args.interval)

    print(f"{'group':<18} {'avg CPU %':>10} {'max CPU %':>10} {'avg MB':>8}")
    for g, vals in series.items():
        cpus = [c for c, _ in vals]
        mems = [m for _, m in vals]
        print(f"{g:<18} {statistics.mean(cpus):>10.1f} {max(cpus):>10.1f} {statistics.mean(mems):>8.0f}")
    print("\n참고: ps의 %CPU는 코어 1개 기준(듀얼코어면 최대 200%)이에요.")


if __name__ == "__main__":
    main()
