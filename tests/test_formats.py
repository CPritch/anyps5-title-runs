import copy
import unittest

from helpers import at

from title_runs import formats

HEAD = "69ac2e155ad018ed1fb9028d2028d15999a8571e"
JOB = formats.job_id(8104, HEAD)
NVIDIA = formats.machine_class("NVIDIA GeForce RTX 5060 Laptop GPU", "Linux 7.2.8")


def good_result():
    return {"format": 1, "job": JOB, "pr": 8104, "head": HEAD, "merge": "7b3f12e95b34" + "0" * 28, "base": "d97361bd0df0" + "0" * 28,
            "machine": "laptop", "tester": "CPritch", "class": NVIDIA, "machine_line": "NVIDIA GeForce RTX 5060 Laptop GPU, NVIDIA 615.71.09, Linux 7.2.8",
            "trust": "queue", "status": "done", "sandbox": "bwrap", "started": "2026-10-21T12:00:00Z", "finished": "2026-10-21T12:50:00Z",
            "titles": {"PPSA04263": {"name": "Grand Theft Auto V", "version": "01.010.002", "scene": "Story Mode, the bank",
                                     "outcome": {"A": "rendering", "B": "rendering"},
                                     "verdict": {"verdict": "no difference beyond the spread", "diff": -0.33, "diff_pct": -0.4, "spread": 0.39, "gpu_diff": 0.07},
                                     "sides": {"A": {"p50": [78.2, 77.9], "p90": [87.6, 89.1], "p99": [108.9, 114.4], "gpu": [63.0, 62.6]},
                                               "B": {"p50": [77.9, 77.5], "p90": [87.9, 88.0], "p99": [109.5, 105.9], "gpu": [63.0, 62.7]}},
                                     "summary_lines": {"A": ['{"commit":"d97361bd0df0"}'], "B": ['{"commit":"7b3f12e95b34"}']}}}}


class Results(unittest.TestCase):
    def test_good(self):
        formats.check_result(good_result(), formats.result_path(JOB, "laptop"))

    def bad(self, change, path=None):
        data = good_result()
        change(data)
        with self.assertRaises(formats.FormatError):
            formats.check_result(data, path)

    def test_wrong_path(self):
        self.bad(lambda d: None, formats.result_path(JOB, "desktop"))

    def test_job_not_the_head(self):
        self.bad(lambda d: d.update(head="1" * 40))

    def test_markup_in_text(self):
        self.bad(lambda d: d.update(machine_line="<img src=x>"))
        self.bad(lambda d: d["titles"]["PPSA04263"]["outcome"].update(B="rendering | x"))
        self.bad(lambda d: d["titles"]["PPSA04263"].update(scene="`code`"))

    def test_summary_lines(self):
        self.bad(lambda d: d["titles"]["PPSA04263"]["summary_lines"]["A"].append("x" * (formats.SUMMARY_LINE_LIMIT + 1)))
        self.bad(lambda d: d["titles"]["PPSA04263"]["summary_lines"]["A"].append("```\n# heading"))

    def test_numbers(self):
        self.bad(lambda d: d["titles"]["PPSA04263"]["sides"]["A"].update(p50=["78"]))
        self.bad(lambda d: d["titles"]["PPSA04263"]["verdict"].update(diff="-0.3"))

    def test_trust_status_sandbox(self):
        self.bad(lambda d: d.update(trust="maintainer"))
        self.bad(lambda d: d.update(status="ok"))
        self.bad(lambda d: d.update(sandbox="docker"))

    def test_verdict_names(self):
        self.bad(lambda d: d["titles"]["PPSA04263"]["verdict"].update(verdict="much faster"))


class Claims(unittest.TestCase):
    def test_round_trip_and_path(self):
        claim = formats.make_claim(JOB, "laptop", "CPritch", NVIDIA, {"PPSA04263"}, at("2026-10-21T12:00:00"), head=HEAD)
        formats.check_claim(claim, formats.claim_path(JOB, "laptop"))
        self.assertEqual(claim["expires"], "2026-10-21T15:00:00Z")
        with self.assertRaises(formats.FormatError):
            formats.check_claim(claim, formats.claim_path(JOB, "desktop"))

    def test_claim_for_another_head_is_refused(self):
        claim = formats.make_claim(JOB, "laptop", "CPritch", NVIDIA, set(), at("2026-10-21T12:00:00"), head="1" * 40)
        with self.assertRaises(formats.FormatError):
            formats.check_claim(claim)

    def test_expiry_more_than_a_day_is_refused(self):
        claim = formats.make_claim(JOB, "laptop", "CPritch", NVIDIA, set(), at("2026-10-21T12:00:00"), hours=30, head=HEAD)
        with self.assertRaises(formats.FormatError):
            formats.check_claim(claim)


class Queue(unittest.TestCase):
    def entry(self):
        return {"job": JOB, "pr": 8104, "head": HEAD, "priority": "normal", "titles": [], "hw": [], "machines": 2,
                "queued_by": "CPritch", "queued_at": "2026-10-21T12:00:00Z", "earlier": [],
                "approval": {"by": "CPritch", "at": "2026-10-21T12:00:00Z", "via": "label"}, "unapproved": []}

    def test_good_and_bad(self):
        queue = formats.empty_queue("CPritch/AnyPS5")
        queue["entries"].append(self.entry())
        formats.check_queue(queue)
        twice = copy.deepcopy(queue)
        twice["entries"].append(self.entry())
        with self.assertRaises(formats.FormatError):
            formats.check_queue(twice)
        carried = copy.deepcopy(queue)
        carried["entries"][0]["approval"] = {"by": "CPritch", "at": "2026-10-21T12:00:00Z", "via": "carried"}
        with self.assertRaises(formats.FormatError):
            formats.check_queue(carried)
        bad = copy.deepcopy(queue)
        bad["entries"][0]["priority"] = "urgent"
        with self.assertRaises(formats.FormatError):
            formats.check_queue(bad)


class Hardware(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(formats.class_key(NVIDIA), "nvidia/linux")
        self.assertEqual(formats.class_key(formats.machine_class("AMD Radeon RX 6700 XT", "Windows 11")), "amd/windows")
        self.assertEqual(formats.class_key(formats.machine_class("Intel(R) Arc(TM) A770", "Windows 11")), "intel/windows")


if __name__ == "__main__":
    unittest.main()
