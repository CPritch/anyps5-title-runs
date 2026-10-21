"""The results repository's files: queue.json, claims and results (FORMATS.md describes them).

Shared by the client and the results repository's workflows (relay/), so standard library only. Every reader checks
what it reads: queue.json is written by the queue workflow, but claims and results come from testers' machines and are
validated before anything is posted from them.
"""

import datetime
import re

FORMAT = 1
PRIORITIES = {"high": 4, "normal": 2, "low": 1}
VENDORS = ("amd", "intel", "nvidia")
SYSTEMS = ("linux", "windows")
CLAIM_HOURS = 3
DEFAULT_MACHINES = 2
TRUST = ("queue", "tester")
STATUSES = ("done", "failed", "superseded")
# protocol.verdict's verdicts.
VERDICTS = ("faster", "slower", "no difference beyond the spread", "not enough counted runs")
SHA = re.compile(r"[0-9a-f]{40}")
JOB = re.compile(r"(\d+)-([0-9a-f]{12})")
MACHINE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
TITLE_ID = re.compile(r"[A-Z]{4}[0-9]{5}")
LOGIN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")


class FormatError(ValueError):
    pass


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def iso(moment):
    return moment.astimezone(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(text):
    if not isinstance(text, str):
        raise FormatError(f"{text!r} is not a time")
    try:
        moment = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise FormatError(f"{text!r} is not an ISO time") from error
    if moment.tzinfo is None:
        raise FormatError(f"{text!r} has no time zone")
    return moment


def job_id(pr, head):
    return f"{int(pr)}-{head[:12]}"


def claim_path(job, machine):
    return f"claims/{job}/{machine}.json"


def result_path(job, machine):
    return f"results/{job}/{machine}.json"


def _need(data, key, kind, where):
    if key not in data:
        raise FormatError(f"{where}: no {key}")
    value = data[key]
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise FormatError(f"{where}: {key} is not {getattr(kind, '__name__', kind)}")
    return value


def _string(data, key, where, pattern=None, limit=200, required=True):
    if key not in data and not required:
        return ""
    value = _need(data, key, str, where)
    if len(value) > limit:
        raise FormatError(f"{where}: {key} is longer than {limit} characters")
    if pattern is not None and not pattern.fullmatch(value):
        raise FormatError(f"{where}: {key} {value!r} is not in the expected form")
    return value


# -- machine classes and hardware tokens ------------------------------------------------------------------------------

def machine_class(gpu, os_name):
    """{"vendor", "os", "gpu"} for a GPU name and an OS name: what hw= tokens are matched against."""
    name = gpu.lower()
    if "nvidia" in name or "geforce" in name:
        vendor = "nvidia"
    elif "amd" in name or "radeon" in name:
        vendor = "amd"
    elif "intel" in name or name.startswith("arc"):
        vendor = "intel"
    else:
        vendor = "other"
    system = "windows" if os_name.lower().startswith("win") else "linux" if "linux" in os_name.lower() else os_name.lower()
    return {"vendor": vendor, "os": system, "gpu": gpu}


def class_key(machine):
    return f"{machine['vendor']}/{machine['os']}"


def hw_token_matches(token, machine):
    """A token is a vendor (amd, intel, nvidia), an OS (linux, windows) or a GPU family: a word sequence that appears in
    the GPU's name (rtx 50, rx 7900, arc a7)."""
    token = token.lower().strip()
    if token in VENDORS:
        return machine["vendor"] == token
    if token in SYSTEMS:
        return machine["os"] == token
    return bool(token) and token in machine["gpu"].lower()


# -- queue.json --------------------------------------------------------------------------------------------------------

def empty_queue(repository):
    return {"format": FORMAT, "repository": repository, "updated": iso(now()), "entries": [], "stopped": [], "cursor": {}}


APPROVALS = ("label", "command", "carried")


def check_entry(entry, where="entry"):
    """A queue entry names the commit a maintainer approved (head), never the branch: testers build that SHA."""
    pr = _need(entry, "pr", int, where)
    head = _string(entry, "head", where, SHA)
    job = _string(entry, "job", where, JOB)
    if job != job_id(pr, head):
        raise FormatError(f"{where}: job {job} is not {job_id(pr, head)}")
    if entry.get("priority") not in PRIORITIES:
        raise FormatError(f"{where}: priority {entry.get('priority')!r} is not one of {', '.join(PRIORITIES)}")
    for key in ("titles", "hw", "earlier"):
        value = entry.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise FormatError(f"{where}: {key} is not a list of strings")
    for sha in entry.get("earlier", []):
        if not SHA.fullmatch(sha):
            raise FormatError(f"{where}: earlier {sha!r} is not a commit SHA")
    approval = _need(entry, "approval", dict, where)
    _string(approval, "by", f"{where} approval", LOGIN)
    parse_time(approval.get("at"))
    if approval.get("via") not in APPROVALS:
        raise FormatError(f"{where}: approval.via {approval.get('via')!r} is not one of {', '.join(APPROVALS)}")
    if approval["via"] == "carried":
        _string(approval, "from", f"{where} approval", SHA)
        _string(approval, "reason", f"{where} approval", TEXT, 200)
    for i, push in enumerate(entry.get("unapproved", [])):
        _string(push, "sha", f"{where} unapproved[{i}]", SHA)
        _string(push, "by", f"{where} unapproved[{i}]", LOGIN)
        parse_time(push.get("at"))
    for title in entry.get("titles", []):
        if not TITLE_ID.fullmatch(title):
            raise FormatError(f"{where}: {title!r} is not a title ID")
    machines = _need(entry, "machines", int, where)
    if not 1 <= machines <= 20:
        raise FormatError(f"{where}: machines {machines} is not between 1 and 20")
    _string(entry, "queued_by", where, LOGIN)
    parse_time(_need(entry, "queued_at", str, where))
    return entry


def check_queue(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise FormatError(f"queue.json: format is not {FORMAT}")
    entries = _need(data, "entries", list, "queue.json")
    seen = set()
    for i, entry in enumerate(entries):
        check_entry(entry, f"queue.json entries[{i}]")
        if entry["pr"] in seen:
            raise FormatError(f"queue.json: #{entry['pr']} is queued twice")
        seen.add(entry["pr"])
    return data


def queue_entry(queue, job):
    return next((e for e in queue["entries"] if e["job"] == job), None)


# -- claims ------------------------------------------------------------------------------------------------------------

def make_claim(job, machine, tester, machine_info, titles, at=None, hours=CLAIM_HOURS, client="", head=None):
    """head: the full SHA the claim is for (the queue entry's approved head); the job id holds its first 12 digits."""
    at = at or now()
    claim = {"format": FORMAT, "job": job, "machine": machine, "tester": tester, "class": machine_info, "titles": sorted(titles),
             "claimed": iso(at), "expires": iso(at + datetime.timedelta(hours=hours)), "client": client}
    if head is not None:
        claim["head"] = head
    return claim


def check_claim(data, path=None):
    where = path or "claim"
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise FormatError(f"{where}: format is not {FORMAT}")
    job = _string(data, "job", where, JOB)
    machine = _string(data, "machine", where, MACHINE)
    _string(data, "tester", where, LOGIN)
    head = _string(data, "head", where, SHA)
    if not job.endswith("-" + head[:12]):
        raise FormatError(f"{where}: head {head[:12]} is not the job's {job}")
    info = _need(data, "class", dict, where)
    for key in ("vendor", "os", "gpu"):
        _string(info, key, f"{where} class", limit=120)
    claimed, expires = parse_time(data.get("claimed")), parse_time(data.get("expires"))
    if not claimed < expires <= claimed + datetime.timedelta(hours=24):
        raise FormatError(f"{where}: expires is not within a day after claimed")
    if path is not None and path != claim_path(job, machine):
        raise FormatError(f"{where}: the file is not at {claim_path(job, machine)}")
    return data


def claim_expired(claim, at=None):
    return parse_time(claim["expires"]) <= (at or now())


# -- results -----------------------------------------------------------------------------------------------------------

SIDE_KEYS = ("p50", "p90", "p99", "gpu")
SUMMARY_LINE_LIMIT = 6000
TEXT = re.compile(r"[^<>`|\r\n\x00-\x08\x0b-\x1f]*")


def check_result(data, path=None):
    """Raises FormatError for anything a tester's machine should not be able to put into a comment: wrong paths and
    ids, unknown statuses, numbers that are not numbers, text with markup characters, oversized summary lines."""
    where = path or "result"
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise FormatError(f"{where}: format is not {FORMAT}")
    job = _string(data, "job", where, JOB)
    pr = _need(data, "pr", int, where)
    head = _string(data, "head", where, SHA)
    if job != job_id(pr, head):
        raise FormatError(f"{where}: job {job} is not {job_id(pr, head)}")
    for key in ("merge", "base"):
        if data.get(key):
            _string(data, key, where, SHA)
    machine = _string(data, "machine", where, MACHINE)
    _string(data, "tester", where, LOGIN)
    if path is not None and path != result_path(job, machine):
        raise FormatError(f"{where}: the file is not at {result_path(job, machine)}")
    if data.get("trust") not in TRUST:
        raise FormatError(f"{where}: trust {data.get('trust')!r} is not one of {', '.join(TRUST)}")
    if data.get("status") not in STATUSES:
        raise FormatError(f"{where}: status {data.get('status')!r} is not one of {', '.join(STATUSES)}")
    if data.get("sandbox") not in ("bwrap", "none"):
        raise FormatError(f"{where}: sandbox {data.get('sandbox')!r} is not bwrap or none")
    _string(data, "machine_line", where, TEXT, 160)
    _string(data, "error", where, TEXT, 300, required=False)
    parse_time(data.get("started"))
    parse_time(data.get("finished"))
    titles = _need(data, "titles", dict, where)
    if len(titles) > 20:
        raise FormatError(f"{where}: more than 20 titles")
    for title_id, entry in titles.items():
        tw = f"{where} titles.{title_id}"
        if not TITLE_ID.fullmatch(title_id):
            raise FormatError(f"{tw}: not a title ID")
        for key, limit in (("name", 80), ("version", 20), ("scene", 120)):
            _string(entry, key, tw, TEXT, limit, required=False)
        outcome = _need(entry, "outcome", dict, tw)
        for side in ("A", "B"):
            _string(outcome, side, f"{tw} outcome", TEXT, 120)
        verdict = entry.get("verdict")
        if verdict is not None:
            if not isinstance(verdict, dict) or verdict.get("verdict") not in VERDICTS:
                raise FormatError(f"{tw}: verdict is not one of {', '.join(VERDICTS)}")
            for key in ("diff", "diff_pct", "spread", "gpu_diff"):
                if verdict.get(key) is not None and not isinstance(verdict[key], (int, float)):
                    raise FormatError(f"{tw}: verdict.{key} is not a number")
        for side, values in (entry.get("sides") or {}).items():
            if side not in ("A", "B") or not isinstance(values, dict):
                raise FormatError(f"{tw}: sides has {side!r}")
            for key in SIDE_KEYS:
                series = values.get(key, [])
                if not isinstance(series, list) or len(series) > 8 or not all(isinstance(v, (int, float)) for v in series):
                    raise FormatError(f"{tw}: sides.{side}.{key} is not a short list of numbers")
        for side, lines in (entry.get("summary_lines") or {}).items():
            if side not in ("A", "B") or not isinstance(lines, list) or len(lines) > 8:
                raise FormatError(f"{tw}: summary_lines.{side} is not a short list")
            for line in lines:
                if not isinstance(line, str) or len(line) > SUMMARY_LINE_LIMIT or "```" in line or "\n" in line:
                    raise FormatError(f"{tw}: a summary line is not one line of at most {SUMMARY_LINE_LIMIT} characters")
    return data


# -- config.json and comments.json -------------------------------------------------------------------------------------

def check_config(data):
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise FormatError(f"config.json: format is not {FORMAT}")
    repository = _string(data, "repository", "config.json", re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+"))
    maintainers = _need(data, "maintainers", list, "config.json")
    if not all(isinstance(m, str) and LOGIN.fullmatch(m) for m in maintainers):
        raise FormatError("config.json: maintainers is not a list of logins")
    testers = _need(data, "testers", dict, "config.json")
    for login, tester in testers.items():
        if not LOGIN.fullmatch(login) or not all(isinstance(m, str) and MACHINE.fullmatch(m) for m in tester.get("machines", [])):
            raise FormatError(f"config.json: testers.{login} is not a login with machine names")
    data.setdefault("label", "title-test")
    return data


def empty_comments():
    return {"format": FORMAT, "prs": {}}
