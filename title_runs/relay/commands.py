"""/title-test commands in comments on AnyPS5's pull requests (DESIGN.md, "The maintainer's controls")."""

import re

from .. import formats

COMMAND = re.compile(r"^/title-test(?:[ \t]+(.*))?$", re.M)
HEX = re.compile(r"[0-9a-f]{7,40}")


class CommandError(ValueError):
    pass


def parse_command(text):
    """The first /title-test line of a comment: {"stop": True} or {"priority", "titles", "hw", "machines", "sha"} with
    None for what the command does not set. Raises CommandError for anything not understood."""
    found = COMMAND.search(text.replace("\r\n", "\n"))
    if not found:
        return None
    out = {"stop": False, "priority": None, "titles": None, "hw": None, "machines": None, "sha": None}
    for token in (found.group(1) or "").split():
        key, eq, value = token.partition("=")
        if not eq:
            if token == "stop":
                out["stop"] = True
            elif token in formats.PRIORITIES:
                out["priority"] = token
            else:
                raise CommandError(f"{token!r} is not a priority or stop")
        elif key == "titles":
            out["titles"] = [t for t in value.split(",") if t]
            if not out["titles"] or not all(formats.TITLE_ID.fullmatch(t) for t in out["titles"]):
                raise CommandError(f"titles={value} is not a list of title IDs")
        elif key == "hw":
            out["hw"] = [t.replace("_", " ").lower() for t in value.split(",") if t]
            if not out["hw"]:
                raise CommandError("hw= is empty")
        elif key == "machines":
            if not value.isdigit() or not 1 <= int(value) <= 20:
                raise CommandError(f"machines={value} is not between 1 and 20")
            out["machines"] = int(value)
        elif key == "sha":
            if not HEX.fullmatch(value.lower()):
                raise CommandError(f"sha={value} is not 7 to 40 hex digits")
            out["sha"] = value.lower()
        else:
            raise CommandError(f"{key}= is not a /title-test option")
    if out["stop"] and any(out[k] is not None for k in ("priority", "titles", "hw", "machines", "sha")):
        raise CommandError("stop takes no options")
    return out
