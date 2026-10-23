"""Controller input for recorded scenarios (DESIGN.md, "Recorded play"): a game controller read from Linux's evdev,
AnyPS5's pad command file (APS5_PAD_INPUT_FILE) written, and a track of recorded play written back.

A state is (buttons, left x, left y, right x, right y): the buttons as main's tools/pad_input.py has them, the sticks 0
to 255 with 128 at rest and 0 at the top and the left. AnyPS5 reads the pad file at most every 100 ms; PadFile writes a
command every STEP_MS with a HOLD_MS hold, so the input stops by itself soon after the writing does.

A track is [[ms, buttons, lx, ly, rx, ry], ...]: the state from that many milliseconds after the start until the next
entry; the last entry, at rest, is where it ends. record() passes a controller through to the game and keeps its
changes; play() writes a track back the same way.
"""

import fcntl
import os
import re
import select
import struct
import time
from pathlib import Path

BUTTONS = {"l3": 0x2, "r3": 0x4, "options": 0x8, "up": 0x10, "right": 0x20, "down": 0x40, "left": 0x80,
           "l2": 0x100, "r2": 0x200, "l1": 0x400, "r1": 0x800, "triangle": 0x1000, "circle": 0x2000, "cross": 0x4000,
           "square": 0x8000, "touchpad": 0x100000}  # main's tools/pad_input.py
ALL_BUTTONS = sum(BUTTONS.values())
NEUTRAL = (0, 128, 128, 128, 128)
STEP_MS = 50  # a command this often: AnyPS5 takes the latest each time it reads the file (at most every 100 ms)
HOLD_MS = 250  # each command's hold: the input stops by itself this long after the writing does
LOCKOUT_MS = 1000  # the first second of a recording is at rest, whatever the controller does
DEADZONE = 12  # a stick this close to 128 is at rest
STICK_STEP = 4  # sticks are kept in steps of this, so a thumb resting on a stick doesn't record noise
MAX_ENTRIES = 100000

# Linux's evdev (linux/input.h, linux/input-event-codes.h). Buttons follow the Linux gamepad layout: south is Cross.
EVENT = struct.Struct("llHHi")  # struct input_event: time (seconds, microseconds), type, code, value
ABSINFO = struct.Struct("6i")  # struct input_absinfo: value, minimum, maximum, fuzz, flat, resolution
EV_KEY, EV_ABS = 1, 3
KEYS = {0x130: "cross", 0x131: "circle", 0x133: "triangle", 0x134: "square", 0x136: "l1", 0x137: "r1", 0x138: "l2",
        0x139: "r2", 0x13a: "touchpad", 0x13b: "options", 0x13d: "l3", 0x13e: "r3",
        0x220: "up", 0x221: "down", 0x222: "left", 0x223: "right"}  # BTN_SOUTH ... BTN_THUMBR, BTN_DPAD_*
STICKS = {0x00: 1, 0x01: 2, 0x03: 3, 0x04: 4}  # ABS_X, ABS_Y, ABS_RX, ABS_RY: their place in a state
TRIGGERS = {0x02: "l2", 0x05: "r2"}  # ABS_Z, ABS_RZ: pressed past a third of their travel
HATS = {0x10: ("left", "right"), 0x11: ("up", "down")}  # ABS_HAT0X, ABS_HAT0Y: the D-pad on most controllers


class PadError(RuntimeError):
    pass


class PadFile:
    """AnyPS5's pad command file: one command, `<sequence> <buttons> <hold ms> <lx> <ly> <rx> <ry>`, replaced whole."""

    def __init__(self, path):
        self.path = Path(path)
        self.sequence = 0

    def write(self, state):
        buttons, lx, ly, rx, ry = state
        self.sequence = max(time.monotonic_ns(), self.sequence + 1)  # as pad_input.py's: it may write the file too
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(f"{self.sequence} {buttons} {HOLD_MS} {lx} {ly} {rx} {ry}\n")
        os.replace(temporary, self.path)


def controllers(devices="/proc/bus/input/devices"):
    """[{"name", "path"}] of the game controllers connected: the input devices with a joystick handler (jsN)."""
    found, block = [], {}
    try:
        lines = Path(devices).read_text().splitlines()
    except OSError:
        return []
    for line in lines + [""]:
        if line.strip():
            key, _, value = line.partition(": ")
            block[key] = value
            continue
        handlers = block.get("H", "")
        event = re.search(r"\bevent\d+\b", handlers)
        if re.search(r"\bjs\d+\b", handlers) and event:
            name = re.sub(r'^Name="(.*)"$', r"\1", block.get("N", ""))
            found.append({"name": name, "path": f"/dev/input/{event.group()}"})
        block = {}
    return found


def settle(value):
    """A stick's 0 to 255, at rest inside the dead zone and in steps of STICK_STEP outside it."""
    if abs(value - 128) <= DEADZONE:
        return 128
    return max(0, min(255, round(value / STICK_STEP) * STICK_STEP))


class Controller:
    """One game controller's evdev device, read without blocking; state() is what it holds now."""

    def __init__(self, path, name="", fd=None):
        self.path, self.name = str(path), name
        self.fd = os.open(self.path, os.O_RDONLY | os.O_NONBLOCK) if fd is None else fd
        self.pressed, self.hats, self.raw, self.ranges = set(), {code: 0 for code in HATS}, {}, {}
        for code in [*STICKS, *TRIGGERS]:
            try:
                value, low, high = ABSINFO.unpack(fcntl.ioctl(self.fd, 0x80184540 + code, bytes(ABSINFO.size)))[:3]  # EVIOCGABS
            except OSError:
                continue
            self.ranges[code], self.raw[code] = (low, high), value

    @classmethod
    def first(cls):
        """The first controller connected; raises PadError when there is none or it can't be read."""
        found = controllers()
        if not found:
            raise PadError("no game controller is connected")
        try:
            return cls(found[0]["path"], found[0]["name"])
        except OSError as error:
            raise PadError(f"can't read {found[0]['name']} ({found[0]['path']}): {error.strerror}") from error

    def close(self):
        os.close(self.fd)

    def apply(self, kind, code, value):
        if kind == EV_KEY and code in KEYS:
            (self.pressed.add if value else self.pressed.discard)(KEYS[code])
        elif kind == EV_ABS and code in HATS:
            self.hats[code] = value
        elif kind == EV_ABS and (code in STICKS or code in TRIGGERS):
            self.raw[code] = value

    def poll(self, timeout=0.0):
        """Take every event waiting (waiting up to timeout seconds for the first)."""
        while select.select([self.fd], [], [], timeout)[0]:
            try:
                data = os.read(self.fd, EVENT.size * 64)
            except BlockingIOError:
                return
            if not data:
                raise PadError(f"{self.name or self.path} was disconnected")
            for offset in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _, _, kind, code, value = EVENT.unpack_from(data, offset)
                self.apply(kind, code, value)
            timeout = 0.0

    def scaled(self, code, default=128):
        if code not in self.raw:
            return default
        low, high = self.ranges.get(code, (0, 255))
        return max(0, min(255, round((self.raw[code] - low) * 255 / ((high - low) or 1))))

    def state(self):
        names = set(self.pressed)
        for code, (negative, positive) in HATS.items():
            if self.hats[code]:
                names.add(negative if self.hats[code] < 0 else positive)
        for code, name in TRIGGERS.items():
            if code in self.raw and self.scaled(code, 0) > 255 // 3:
                names.add(name)
        sticks = [128] * 4
        for code, place in STICKS.items():
            sticks[place - 1] = settle(self.scaled(code))
        return (sum(BUTTONS[name] for name in names), *sticks)


def _paced(clock, sleep, start, step):
    sleep(max(0.0, start + step * STEP_MS / 1000 - clock()))


def record(controller, pad_file, seconds, should_stop=lambda: None, progress=None, clock=time.monotonic, sleep=time.sleep):
    """Pass the controller through to the game for seconds (at rest for the first LOCKOUT_MS), and return the track:
    the state at each change. Ends early, with what was recorded so far, when should_stop() says why."""
    track, last, start, step, second = [], None, clock(), 0, -1
    try:
        while True:
            elapsed = int((clock() - start) * 1000)
            if elapsed >= seconds * 1000 or should_stop():
                break
            controller.poll()
            state = NEUTRAL if elapsed < LOCKOUT_MS else controller.state()
            pad_file.write(state)
            if state != last:
                track.append([elapsed, *state])
                last = state
            if progress and elapsed // 1000 != second:
                second = elapsed // 1000
                progress(second)
            step += 1
            _paced(clock, sleep, start, step)
    finally:
        pad_file.write(NEUTRAL)
    track.append([min(elapsed, seconds * 1000), *NEUTRAL])
    return track


def play(track, pad_file, should_stop=lambda: None, clock=time.monotonic, sleep=time.sleep):
    """Write the track to the game from now, a state every STEP_MS, until its end or should_stop(). Returns how many
    milliseconds of it were played."""
    start, step, index, end = clock(), 0, 0, track[-1][0]
    elapsed = 0
    try:
        while True:
            elapsed = int((clock() - start) * 1000)
            if elapsed >= end or should_stop():
                break
            while index + 1 < len(track) and track[index + 1][0] <= elapsed:
                index += 1
            pad_file.write(tuple(track[index][1:]))
            step += 1
            _paced(clock, sleep, start, step)
    finally:
        pad_file.write(NEUTRAL)
    return min(elapsed, end)


def check_track(track):
    """Raises PadError unless track is a track: entries of six whole numbers, times from 0 rising, known buttons,
    sticks 0 to 255, ending at rest within an hour."""
    if not isinstance(track, list) or not 2 <= len(track) <= MAX_ENTRIES:
        raise PadError(f"a track has 2 to {MAX_ENTRIES} entries")
    previous = -1
    for index, entry in enumerate(track):
        if not isinstance(entry, list) or len(entry) != 6 or not all(type(value) is int for value in entry):
            raise PadError(f"track[{index}] is not six whole numbers")
        at, buttons, *sticks = entry
        if at < previous or at > 3600000 or (index == 0 and at != 0):
            raise PadError(f"track[{index}]: the times start at 0 and rise, within an hour")
        if buttons & ~ALL_BUTTONS or buttons < 0 or not all(0 <= stick <= 255 for stick in sticks):
            raise PadError(f"track[{index}]: unknown buttons, or a stick outside 0 to 255")
        previous = at
    if tuple(track[-1][1:]) != NEUTRAL:
        raise PadError("a track ends at rest")


def button_words(name):
    return name.upper() if len(name) == 2 else f"D-pad {name}" if name in ("up", "down", "left", "right") else name.capitalize()


def words(track):
    """What a track uses, for the report: "152 s: the sticks, Cross and R2"."""
    used, sticks = 0, False
    for _, buttons, *axes in track:
        used |= buttons
        sticks = sticks or any(axis != 128 for axis in axes)
    parts = (["the sticks"] if sticks else []) + [button_words(name) for name, bit in BUTTONS.items() if used & bit]
    said = ", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0] if parts else "nothing pressed"
    return f"{track[-1][0] / 1000:.0f} s: {said}"
