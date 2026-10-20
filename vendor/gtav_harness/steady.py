#!/usr/bin/env python3
"""Read APS5_TRACE_SUMMARY_EVERY lines (aps5-summary.jsonl) for load detection and benchmarks.

Usage:
  steady.py now <summary.jsonl>
      prints the end of the latest interval, in seconds after the first present (0 if none)
  steady.py loaded <summary.jsonl> <after_s> [max_p50_ms]
      exit 0 when the last two intervals that start after <after_s> each have a p50 frame
      time at or below max_p50_ms (default 1000) and a max below 5x their p50
  steady.py window <summary.jsonl> <start_s> <end_s>
      one line for the intervals that lie inside [start_s, end_s]: the median of their p50s
      and p90s, the largest p99 and max, the mean GPU busy time per present, presents, and
      the phase that tops the most intervals
"""
import json
import statistics
import sys


def intervals(path):
    out = []
    try:
        for line in open(path):
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if "interval_start_s" in row and row.get("frame_ms"):
                out.append(row)
    except FileNotFoundError:
        pass
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "now" and len(sys.argv) == 3:
        rows = intervals(sys.argv[2])
        print(f"{rows[-1]['interval_end_s']:.1f}" if rows else "0")
    elif mode == "loaded" and len(sys.argv) in (4, 5):
        after = float(sys.argv[3])
        limit = float(sys.argv[4]) if len(sys.argv) == 5 else 1000.0
        rows = [r for r in intervals(sys.argv[2]) if r["interval_start_s"] >= after]
        last = rows[-2:]
        ok = len(last) == 2 and all(
            r["frame_ms"]["p50"] <= limit and r["frame_ms"]["max"] < 5 * r["frame_ms"]["p50"] for r in last)
        sys.exit(0 if ok else 1)
    elif mode == "window" and len(sys.argv) == 5:
        start, end = float(sys.argv[3]), float(sys.argv[4])
        rows = [r for r in intervals(sys.argv[2]) if r["interval_start_s"] >= start and r["interval_end_s"] <= end]
        if not rows:
            print("steady: no complete interval in the window")
            sys.exit(1)
        p50 = statistics.median(r["frame_ms"]["p50"] for r in rows)
        p90 = statistics.median(r["frame_ms"]["p90"] for r in rows)
        p99 = max(r["frame_ms"]["p99"] for r in rows)
        worst = max(r["frame_ms"]["max"] for r in rows)
        gpu = statistics.mean(r.get("gpu_busy_ms_per_present", 0) for r in rows)
        presents = sum(r["presents"] for r in rows)
        tops = [max(r["top_phases_ms_per_frame"], key=r["top_phases_ms_per_frame"].get)
                for r in rows if r.get("top_phases_ms_per_frame")]
        top = statistics.mode(tops) if tops else "n/a"
        print(f"steady: {len(rows)} intervals {rows[0]['interval_start_s']:.0f}-{rows[-1]['interval_end_s']:.0f} s, "
              f"p50 {p50:.1f} ms ({1000 / p50:.1f} fps), p90 {p90:.1f} ms, p99 {p99:.1f} ms, max {worst:.1f} ms, "
              f"GPU {gpu:.1f} ms/present, {presents} presents, top phase {top}")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
