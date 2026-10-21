"""The client's choice of its next job: DESIGN.md's score, with the reasons shown in the Queue tab.

    score = priority weight × hardware match × title match × coverage gap × age

- priority weight: high 4, normal 2, low 1;
- hardware match: 1 if a token in hw= matches this machine, 0.5 if hw= is empty, 0 if hw= names only other machines;
- title match: 1 if the tester has a wanted title (or titles= is empty and the tester has any), 0 otherwise;
- coverage gap: 0 if this machine has already reported this head, if machines= is met by machines that reported or hold
  a live claim, or if another machine of this class holds a live claim (two testers of one class do not run the same
  head at once); 0.2 if a machine of this class has reported this head; 1 otherwise. Expired claims count for nothing.
  A class whose combined verdict is borderline (verdict.combine) wants another machine of it until class_max (the results repository's config.json) have
  reported: 1 for a machine of that class, even when machines= is met;
- age: 1 + hours waited / AGE_HOURS, at most AGE_CAP (a low-priority entry waiting two days weighs as a fresh normal
  one).
"""

from dataclasses import dataclass, field

from . import formats, verdict

AGE_HOURS = 48.0
AGE_CAP = 2.0
COVERED_ONCE = 0.2


@dataclass
class Machine:
    name: str
    tester: str
    info: dict
    titles: set = field(default_factory=set)


@dataclass
class Choice:
    entry: dict
    score: float
    factors: dict
    reasons: list

    @property
    def job(self):
        return self.entry["job"]


def priority_weight(entry):
    return formats.PRIORITIES[entry["priority"]], f"{entry['priority']} priority ×{formats.PRIORITIES[entry['priority']]}"


def hardware_match(entry, machine):
    hw = entry.get("hw", [])
    if not hw:
        return 0.5, "any hardware ×0.5"
    matched = [t for t in hw if formats.hw_token_matches(t, machine.info)]
    if matched:
        return 1.0, f"hardware {','.join(matched)} wanted ×1"
    return 0.0, f"hardware wanted is {','.join(hw)}, this machine is {formats.class_key(machine.info)} ×0"


def title_match(entry, machine):
    wanted = entry.get("titles", [])
    if not wanted:
        return (1.0, "any title ×1") if machine.titles else (0.0, "this machine has no titles ×0")
    have = sorted(set(wanted) & machine.titles)
    if have:
        return 1.0, f"title {','.join(have)} wanted ×1"
    return 0.0, f"titles wanted are {','.join(wanted)}, none here ×0"


def coverage_gap(entry, machine, claims, results, at, rules=verdict.DEFAULT):
    """claims and results: {job: {machine: data}} as read from the results repository."""
    job = entry["job"]
    reported = {m: r for m, r in (results.get(job) or {}).items() if r.get("status") == "done"}
    live = {m: c for m, c in (claims.get(job) or {}).items() if not formats.claim_expired(c, at) and m not in reported}
    if machine.name in reported:
        return 0.0, "this machine has reported this head ×0"
    mine = verdict.class_of(machine.info)
    for title_id in sorted(machine.titles):
        combined = verdict.by_class(reported, title_id, rules).get(mine)
        if combined and combined["borderline"] and combined["n"] < rules.class_max:
            return 1.0, f"{mine}: borderline on {combined['n']} machine(s), another wanted ×1"
    others = {m: c for m, c in live.items() if m != machine.name}
    if len(reported) + len(others) >= entry["machines"]:
        return 0.0, f"{entry['machines']} machine(s) wanted, {len(reported)} reported and {len(others)} claimed ×0"
    # The class verdicts are combined in (GPU model, driver branch, OS), not the vendor and OS that hw= matches.
    if any(verdict.class_of(c["class"]) == mine for c in others.values()):
        return 0.0, f"another {mine} machine holds a claim ×0"
    if any(verdict.class_of(r["class"]) == mine for r in reported.values()):
        return COVERED_ONCE, f"a {mine} machine has reported this head ×{COVERED_ONCE}"
    return 1.0, f"no {mine} report yet ×1"


def age(entry, at):
    hours = max(0.0, (at - formats.parse_time(entry["queued_at"])).total_seconds() / 3600)
    factor = min(AGE_CAP, 1 + hours / AGE_HOURS)
    return factor, f"waited {hours:.0f} h ×{factor:.2f}"


def score(entry, machine, claims, results, at, rules=verdict.DEFAULT):
    factors, reasons = {}, []
    total = 1.0
    for name, (value, reason) in (("priority", priority_weight(entry)), ("hardware", hardware_match(entry, machine)),
                                  ("titles", title_match(entry, machine)),
                                  ("coverage", coverage_gap(entry, machine, claims, results, at, rules)), ("age", age(entry, at))):
        factors[name] = value
        reasons.append(reason)
        total *= value
    return Choice(entry, total, factors, reasons)


def rank(queue, machine, claims, results, at=None, rules=verdict.DEFAULT):
    """Every queue entry with its score, best first (ties: older entry first, then the lower PR number)."""
    at = at or formats.now()
    choices = [score(entry, machine, claims, results, at, rules) for entry in queue.get("entries", [])]
    return sorted(choices, key=lambda c: (-c.score, c.entry["queued_at"], c.entry["pr"]))


def choose(queue, machine, claims, results, at=None, rules=verdict.DEFAULT):
    """The job to run next, or None when every entry scores 0."""
    best = next(iter(rank(queue, machine, claims, results, at, rules)), None)
    return best if best is not None and best.score > 0 else None
