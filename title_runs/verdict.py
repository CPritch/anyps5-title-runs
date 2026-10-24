"""Verdicts (DESIGN.md, "Verdicts"): per machine, and combined over the machines of one class.

Per machine, the difference of the mean p50s (PR - main) counts only when it is larger than both sides' spreads and
larger than threshold_pct (1 %) of main's mean p50. A difference that passes one of the two tests and not the other is
borderline. Machines of one class (GPU model, driver branch, OS) are combined by their per-machine differences, never
by raw frame times.
"""

import re
import statistics
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """threshold_pct, the share of main's p50 a difference must exceed; class_max, how many machines a borderline class
    wants at most."""
    threshold_pct: float = 1.0
    class_max: int = 3


DEFAULT = Settings()


def spread(values):
    return max(values) - min(values) if values else 0.0


def machine(sides, rules=DEFAULT):
    """The verdict of one machine's A/B from its sides ({"A": {"p50": [...], "gpu": [...]}, "B": ...}): verdict
    (faster, slower, no difference, not enough counted runs), diff and diff_pct (PR - main), main_fps and pr_fps (from
    each side's median frame time), spread, size (threshold_pct of main), gpu_diff, borderline."""
    a, b = (sides.get(k) or {} for k in ("A", "B"))
    pa, pb = a.get("p50") or [], b.get("p50") or []
    if len(pa) < 2 or len(pb) < 2:
        return {"verdict": "not enough counted runs", "diff": None, "borderline": False}
    main_p50 = statistics.mean(pa)
    diff = statistics.mean(pb) - main_p50
    noise = max(spread(pa), spread(pb))
    size = rules.threshold_pct / 100 * main_p50
    beyond_spread, beyond_size = abs(diff) > noise, abs(diff) > size
    if beyond_spread and beyond_size:
        word = "faster" if diff < 0 else "slower"
    else:
        word = "no difference"
    gpu = None
    if a.get("gpu") and b.get("gpu"):
        gpu = statistics.mean(b["gpu"]) - statistics.mean(a["gpu"])
    return {"verdict": word, "diff": diff, "diff_pct": diff / main_p50 * 100, "main_fps": 1000 / main_p50,
            "pr_fps": 1000 / statistics.mean(pb), "spread": noise, "size": size, "gpu_diff": gpu, "borderline": beyond_spread != beyond_size}


def driver_branch(driver):
    """NVIDIA 615.71.09 -> NVIDIA 615; Mesa 24.2.1 -> Mesa 24.2; 32.0.21045.5002 -> 32.0 (AMD and Intel on Windows)."""
    driver = (driver or "").strip()
    found = re.match(r"(?:(NVIDIA|Mesa)\s+)?(\d+)(?:\.(\d+))?", driver, re.I)
    if not found:
        return driver or "unknown driver"
    vendor, first, second = found.groups()
    if vendor and vendor.lower() == "nvidia":
        return f"NVIDIA {first}"
    if vendor:
        return f"Mesa {first}.{second}" if second else f"Mesa {first}"
    return f"{first}.{second}" if second else first


def os_family(name):
    """Linux 7.2.8-zen1 -> Linux; Windows 11 (10.0.26200) -> Windows 11."""
    name = (name or "").strip()
    if name.lower().startswith("windows"):
        found = re.match(r"(Windows\s+\S+)", name)
        return found.group(1) if found else "Windows"
    return name.split()[0] if name else "unknown OS"


def short_gpu(gpu):
    return re.sub(r"^(NVIDIA GeForce|NVIDIA|AMD Radeon|AMD|Intel\(R\)|Intel)\s+", "", (gpu or "").strip()).replace("(TM)", "").strip() or "unknown GPU"


def class_of(info):
    """The class a machine's results are combined in: GPU model, driver branch, OS family."""
    return f"{short_gpu(info.get('gpu'))} · {driver_branch(info.get('driver'))} · {os_family(info.get('os_name') or info.get('os'))}"


def combine(name, verdicts, rules=DEFAULT):
    """One class's machines ({machine: machine() verdict}) combined: verdict (faster, slower, mixed, no difference),
    count (machines with that verdict), n, median_diff, median_pct, borderline, text."""
    counted = {m: v for m, v in verdicts.items() if v.get("diff") is not None}
    n = len(counted)
    if not n:
        return {"class": name, "n": 0, "verdict": "not enough counted runs", "count": 0, "borderline": False,
                "text": f"Not enough counted runs on {name} machines"}
    words = [v["verdict"] for v in counted.values()]
    faster, slower = words.count("faster"), words.count("slower")
    if faster and slower:
        word, count = "mixed", n
    elif faster > n / 2:
        word, count = "faster", faster
    elif slower > n / 2:
        word, count = "slower", slower
    else:
        word, count = "no difference", words.count("no difference")
    median = statistics.median(v["diff"] for v in counted.values())
    median_pct = statistics.median(v["diff_pct"] for v in counted.values())
    disagree = len(set(words)) > 1
    borderline = (n == 1 and next(iter(counted.values()))["borderline"]) or (disagree and n < rules.class_max)
    lead = {"mixed": "Mixed", "faster": "Faster", "slower": "Slower", "no difference": "No difference"}[word]
    if word == "mixed":
        text = f"Mixed on {n} {name} machine{'s' if n > 1 else ''} ({faster} faster, {slower} slower), median {median:+.2f} ms ({median_pct:+.1f} %)"
    else:
        text = f"{lead} on {count} of {n} {name} machine{'s' if n > 1 else ''}, median {median:+.2f} ms ({median_pct:+.1f} %)"
    if borderline and n < rules.class_max:
        text += "; borderline, one more machine of this class wanted"
    return {"class": name, "n": n, "verdict": word, "count": count, "median_diff": median, "median_pct": median_pct,
            "borderline": borderline, "text": text}


def by_class(results, title_id, rules=DEFAULT):
    """{class: combine()} for one title over results ({machine: result file}), done results only. Each verdict is
    recomputed from the result's sides. Results timed in a scenario (scenarios.py) are combined only with the same
    scenario's: their class reads "<class> in <scenario id>"."""
    groups = {}
    for name, result in results.items():
        if result.get("status") != "done" or title_id not in result.get("titles", {}):
            continue
        info = result.get("class") or {}
        entry = result["titles"][title_id]
        key = class_of(info) + (f" in {entry['scenario']}" if entry.get("scenario") else "")
        groups.setdefault(key, {})[name] = machine(entry.get("sides") or {}, rules)
    return {key: combine(key, verdicts, rules) for key, verdicts in sorted(groups.items())}
