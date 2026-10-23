"""Controller input (pad.py): the pad file in the form AnyPS5 reads, controllers found and read from evdev, a recording
passing the controller through (at rest for its first second), and a track played back at its times."""

import os
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401

from title_runs import pad

DEVICES = '''I: Bus=0003 Vendor=046d Product=c077 Version=0111
N: Name="HP USB Laser Mouse"
H: Handlers=mouse0 event4

I: Bus=0005 Vendor=054c Product=0ce6 Version=8100
N: Name="Sony Interactive Entertainment DualSense Wireless Controller"
H: Handlers=event20 js0

I: Bus=0005 Vendor=054c Product=0ce6 Version=8100
N: Name="Sony Interactive Entertainment DualSense Wireless Controller Motion Sensors"
H: Handlers=event21

I: Bus=0005 Vendor=054c Product=0ce6 Version=8100
N: Name="Sony Interactive Entertainment DualSense Wireless Controller Touchpad"
H: Handlers=mouse2 event22
'''


class Clock:
    """time.monotonic and time.sleep, standing still until slept."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Written:
    """A PadFile that keeps what was written, with the clock's time in milliseconds."""

    def __init__(self, clock):
        self.clock, self.states = clock, []

    def write(self, state):
        self.states.append((round((self.clock() - 1000.0) * 1000), tuple(state)))


def anyps5_reads(line):
    """InputCommandFile.hpp's checks on a command line: seven whole numbers, a sequence, known buttons, a hold of 1 to 5000
    ms, sticks up to 255."""
    values = [int(token) for token in line.split()]
    return (len(values) == 7 and values[0] > 0 and not values[1] & ~(0x10fffe | 0x200000 | 0x400000)
            and 1 <= values[2] <= 5000 and all(v <= 255 for v in values[3:]))


class PadFile(unittest.TestCase):
    def test_a_command_anyps5_reads_with_a_rising_sequence(self):
        path = Path(tempfile.mkdtemp()) / "pad-input"
        out = pad.PadFile(path)
        out.write((pad.BUTTONS["cross"], 0, 128, 255, 128))
        first = path.read_text()
        out.write(pad.NEUTRAL)
        second = path.read_text()
        self.assertTrue(anyps5_reads(first) and anyps5_reads(second), (first, second))
        self.assertEqual(first.split()[1:], ["16384", "250", "0", "128", "255", "128"])
        self.assertGreater(int(second.split()[0]), int(first.split()[0]))
        self.assertEqual(list(path.parent.iterdir()), [path])  # replaced whole, nothing left beside it


class Controllers(unittest.TestCase):
    def test_the_device_with_a_joystick_handler(self):
        devices = Path(tempfile.mkdtemp()) / "devices"
        devices.write_text(DEVICES)
        self.assertEqual(pad.controllers(devices), [{"name": "Sony Interactive Entertainment DualSense Wireless Controller", "path": "/dev/input/event20"}])
        self.assertEqual(pad.controllers(devices.parent / "none"), [])

    def test_events_make_a_state(self):
        read, write = os.pipe()
        controller = pad.Controller("pipe", "test pad", fd=read)  # no EVIOCGABS on a pipe: 0 to 255 then
        controller.ranges[0x00] = (-32768, 32767)  # an Xbox controller's left stick
        events = [(pad.EV_KEY, 0x130, 1), (pad.EV_ABS, 0x00, -32768), (pad.EV_ABS, 0x11, -1), (pad.EV_ABS, 0x05, 200),
                  (pad.EV_ABS, 0x04, 131), (pad.EV_KEY, 0x13a, 1), (0, 0, 0)]
        os.write(write, b"".join(pad.EVENT.pack(1, 0, kind, code, value) for kind, code, value in events))
        controller.poll()
        buttons, lx, ly, rx, ry = controller.state()
        self.assertEqual(buttons, pad.BUTTONS["cross"] | pad.BUTTONS["up"] | pad.BUTTONS["r2"] | pad.BUTTONS["touchpad"])
        self.assertEqual((lx, ly, rx, ry), (0, 128, 128, 128))  # 131 is inside the dead zone
        os.write(write, pad.EVENT.pack(1, 0, pad.EV_KEY, 0x130, 0) + pad.EVENT.pack(1, 0, pad.EV_ABS, 0x05, 10))
        controller.poll()
        self.assertEqual(controller.state()[0], pad.BUTTONS["up"] | pad.BUTTONS["touchpad"])
        os.close(write)
        with self.assertRaises(pad.PadError):
            controller.poll()  # unplugged
        controller.close()

    def test_sticks_settle(self):
        self.assertEqual([pad.settle(v) for v in (0, 117, 128, 139, 141, 200, 255)], [0, 128, 128, 128, 140, 200, 255])


class Recording(unittest.TestCase):
    def test_the_controller_passes_through_and_its_changes_are_kept(self):
        clock = Clock()
        out = Written(clock)

        class Played:
            def poll(self):
                pass

            def state(self):
                at = clock() - 1000.0
                if at < 2:
                    return (pad.BUTTONS["cross"], 128, 128, 128, 128)  # held from the start: locked out for the first second
                if at < 3:
                    return (0, 128, 0, 128, 128)  # walking forward
                return pad.NEUTRAL

        seconds = []
        track = pad.record(Played(), out, 4, progress=seconds.append, clock=clock, sleep=clock.sleep)
        self.assertEqual(track, [[0, *pad.NEUTRAL], [1000, pad.BUTTONS["cross"], 128, 128, 128, 128], [2000, 0, 128, 0, 128, 128],
                                 [3000, *pad.NEUTRAL], [4000, *pad.NEUTRAL]])
        self.assertEqual(seconds, [0, 1, 2, 3])
        self.assertEqual(out.states[0], (0, pad.NEUTRAL))
        self.assertEqual(out.states[20], (1000, (pad.BUTTONS["cross"], 128, 128, 128, 128)))  # every 50 ms
        self.assertEqual(out.states[-1], (4000, pad.NEUTRAL))  # at rest when it ends
        pad.check_track(track)

    def test_stopping_keeps_what_was_recorded(self):
        clock = Clock()
        track = pad.record(type("Still", (), {"poll": lambda self: None, "state": lambda self: pad.NEUTRAL})(), Written(clock), 60,
                           should_stop=lambda: "stopped" if clock() - 1000.0 >= 2 else None, clock=clock, sleep=clock.sleep)
        self.assertEqual(track[-1], [2000, *pad.NEUTRAL])


class Playing(unittest.TestCase):
    def test_each_state_at_its_time(self):
        clock = Clock()
        out = Written(clock)
        track = [[0, *pad.NEUTRAL], [1000, 0, 128, 0, 128, 128], [1500, pad.BUTTONS["cross"], 128, 0, 128, 128], [2000, *pad.NEUTRAL]]
        self.assertEqual(pad.play(track, out, clock=clock, sleep=clock.sleep), 2000)
        states = dict(out.states[:-1])
        self.assertEqual((states[950], states[1000], states[1450], states[1500]),
                         (pad.NEUTRAL, (0, 128, 0, 128, 128), (0, 128, 0, 128, 128), (pad.BUTTONS["cross"], 128, 0, 128, 128)))
        self.assertEqual(out.states[-1], (2000, pad.NEUTRAL))

    def test_stopped_part_way(self):
        clock = Clock()
        track = [[0, 0, 128, 0, 128, 128], [10000, *pad.NEUTRAL]]
        played = pad.play(track, Written(clock), should_stop=lambda: clock() - 1000.0 >= 3, clock=clock, sleep=clock.sleep)
        self.assertEqual(played, 3000)


class Tracks(unittest.TestCase):
    def test_what_a_track_may_be(self):
        good = [[0, *pad.NEUTRAL], [1000, pad.BUTTONS["r2"], 128, 0, 128, 128], [5000, *pad.NEUTRAL]]
        pad.check_track(good)
        for bad in ([], [[0, *pad.NEUTRAL]], [[5, *pad.NEUTRAL], [10, *pad.NEUTRAL]], [[0, *pad.NEUTRAL], [10, 1 << 30, 128, 128, 128, 128], [20, *pad.NEUTRAL]],
                    [[0, *pad.NEUTRAL], [10, 0, 300, 128, 128, 128], [20, *pad.NEUTRAL]], [[0, *pad.NEUTRAL], [10, 0, 0, 128, 128, 128]],
                    [[0, *pad.NEUTRAL], [20, *pad.NEUTRAL], [10, *pad.NEUTRAL]], [[0, 0, 128, 128, 128, 128.5], [10, *pad.NEUTRAL]]):
            with self.subTest(bad=bad), self.assertRaises(pad.PadError):
                pad.check_track(bad)
        self.assertEqual(pad.words(good), "5 s: the sticks and R2")
        self.assertEqual(pad.words([[0, *pad.NEUTRAL], [3000, *pad.NEUTRAL]]), "3 s: nothing pressed")


if __name__ == "__main__":
    unittest.main()
