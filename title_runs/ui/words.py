"""Who runs the testing, as the tester reads it: the results repository's config.json "team" (CPritch, or the AnyPS5
team once they adopt it), and a neutral default until the tester has joined. The app never claims an affiliation the
config doesn't."""

DEFAULT = "whoever runs this testing"
_team = [DEFAULT]


def set_team(name):
    _team[0] = (name or "").strip() or DEFAULT


def team():
    """The team's name mid-sentence: "approved by CPritch"."""
    return _team[0]


def Team():  # noqa: N802 (the capitalised form, for the start of a sentence)
    name = _team[0]
    return name[:1].upper() + name[1:]
