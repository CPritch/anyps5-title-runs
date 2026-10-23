"""Times, job IDs and machine classes, as the rest of the tool reads and writes them."""

import datetime


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


def utc_text(stamp):
    """A time as people read it: "2026-10-23 16:38 UTC" ("?" for one that isn't a time)."""
    try:
        return parse_time(stamp).astimezone(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except FormatError:
        return "?"


def job_id(pr, head):
    return f"{int(pr)}-{head[:12]}"


# -- machine classes ---------------------------------------------------------------------------------------------------

def machine_class(gpu, os_name, driver=""):
    """{"vendor", "os", "gpu", "driver", "os_name"} for a GPU name, an OS name and a driver version: GPU, driver and the
    OS name give the class results are combined in (verdict.class_of)."""
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
    return {"vendor": vendor, "os": system, "gpu": gpu, "driver": driver, "os_name": os_name}
