"""Verdicts (DESIGN.md, "Verdicts"): per machine with the 1 % rule, combined per class, and the scheduler asking for
another machine of a borderline class."""

import unittest

from helpers import at

from title_runs import formats, schedule, verdict

LAPTOP = formats.machine_class("NVIDIA GeForce RTX 5060 Laptop GPU", "Linux 7.2.8-zen1-2-zen", "NVIDIA 615.71.09")
LAPTOP_TOO = formats.machine_class("NVIDIA GeForce RTX 5060 Laptop GPU", "Linux 6.17.1-arch1", "NVIDIA 615.42.01")
DESKTOP = formats.machine_class("NVIDIA GeForce RTX 4060", "Linux 6.17", "NVIDIA 580.126.20")
HEAD = "69ac2e155ad018ed1fb9028d2028d15999a8571e"


def sides(a, b):
    return {"A": {"p50": list(a), "gpu": [60.0, 60.0]}, "B": {"p50": list(b), "gpu": [59.0, 59.0]}}


def result(name, info, a, b, status="done"):
    return {"job": formats.job_id(8104, HEAD), "machine": name, "class": info, "status": status,
            "titles": {"PPSA04263": {"outcome": {"A": "rendering", "B": "rendering"}, "sides": sides(a, b)}}}


class PerMachine(unittest.TestCase):
    def test_round_2s_no_op_is_no_difference_and_borderline(self):
        v = verdict.machine(sides((78.0, 78.0), (77.6, 77.7)))
        self.assertEqual(v["verdict"], "no difference")
        self.assertAlmostEqual(v["diff"], -0.35)
        self.assertTrue(v["borderline"])  # beyond the spread (0.1) but not beyond 1 % (0.78)

    def test_a_clear_difference(self):
        v = verdict.machine(sides((79.7, 79.1), (72.1, 72.7)))
        self.assertEqual((v["verdict"], v["borderline"]), ("faster", False))
        self.assertAlmostEqual(v["diff_pct"], -8.816, places=3)

    def test_slower(self):
        self.assertEqual(verdict.machine(sides((70.0, 70.2), (72.0, 72.1)))["verdict"], "slower")

    def test_large_but_noisy_is_borderline(self):
        v = verdict.machine(sides((78.0, 80.0), (76.8, 77.2)))  # diff -2.0 > 1 % (0.79) but not > spread (2.0)
        self.assertEqual((v["verdict"], v["borderline"]), ("no difference", True))

    def test_inside_both(self):
        v = verdict.machine(sides((78.0, 78.4), (78.1, 78.3)))
        self.assertEqual((v["verdict"], v["borderline"]), ("no difference", False))

    def test_not_enough_runs(self):
        self.assertEqual(verdict.machine(sides((78.0,), (77.0, 77.1)))["verdict"], "not enough counted runs")


class Classes(unittest.TestCase):
    def test_class_key(self):
        self.assertEqual(verdict.class_of(LAPTOP), "RTX 5060 Laptop GPU · NVIDIA 615 · Linux")
        self.assertEqual(verdict.class_of(LAPTOP), verdict.class_of(LAPTOP_TOO))
        self.assertNotEqual(verdict.class_of(LAPTOP), verdict.class_of(DESKTOP))
        self.assertEqual(verdict.driver_branch("Mesa 24.2.1"), "Mesa 24.2")
        self.assertEqual(verdict.driver_branch("32.0.21045.5002"), "32.0")
        self.assertEqual(verdict.os_family("Windows 11 (10.0.26200)"), "Windows 11")

    def test_three_of_three_faster(self):
        results = {f"m{i}": result(f"m{i}", LAPTOP, (79.7, 79.1), (72.1 + i / 10, 72.7)) for i in range(3)}
        combined = verdict.by_class(results, "PPSA04263")["RTX 5060 Laptop GPU · NVIDIA 615 · Linux"]
        self.assertEqual((combined["verdict"], combined["count"], combined["n"], combined["borderline"]), ("faster", 3, 3, False))
        self.assertTrue(combined["text"].startswith("Faster on 3 of 3 RTX 5060 Laptop GPU · NVIDIA 615 · Linux machines, median -6.95 ms (-8.8 %)"))

    def test_classes_are_kept_apart_and_frame_times_are_never_pooled(self):
        results = {"laptop": result("laptop", LAPTOP, (79.7, 79.1), (72.1, 72.7)), "desktop": result("desktop", DESKTOP, (95.0, 95.1), (94.8, 95.0))}
        combined = verdict.by_class(results, "PPSA04263")
        self.assertEqual({k: v["verdict"] for k, v in combined.items()},
                         {"RTX 5060 Laptop GPU · NVIDIA 615 · Linux": "faster", "RTX 4060 · NVIDIA 580 · Linux": "no difference"})

    def test_one_borderline_machine_asks_for_another(self):
        combined = verdict.by_class({"laptop": result("laptop", LAPTOP, (78.0, 78.0), (77.6, 77.7))}, "PPSA04263")
        (only,) = combined.values()
        self.assertTrue(only["borderline"])
        self.assertIn("one more machine of this class wanted", only["text"])

    def test_a_second_machine_settles_it(self):
        results = {"laptop": result("laptop", LAPTOP, (78.0, 78.0), (77.6, 77.7)), "laptop-2": result("laptop-2", LAPTOP_TOO, (78.1, 77.8), (78.2, 77.9))}
        (only,) = verdict.by_class(results, "PPSA04263").values()
        self.assertEqual((only["verdict"], only["count"], only["n"], only["borderline"]), ("no difference", 2, 2, False))
        self.assertAlmostEqual(only["median_diff"], (-0.35 + 0.1) / 2)

    def test_disagreement_is_borderline_until_three(self):
        two = {"a": result("a", LAPTOP, (79.7, 79.1), (72.1, 72.7)), "b": result("b", LAPTOP_TOO, (78.1, 77.8), (78.2, 77.9))}
        (combined,) = verdict.by_class(two, "PPSA04263").values()
        self.assertEqual((combined["verdict"], combined["borderline"]), ("no difference", True))
        three = {**two, "c": result("c", LAPTOP, (79.7, 79.1), (72.3, 72.5))}
        (combined,) = verdict.by_class(three, "PPSA04263").values()
        self.assertEqual((combined["verdict"], combined["count"], combined["borderline"]), ("faster", 2, False))

    def test_mixed(self):
        results = {"a": result("a", LAPTOP, (79.7, 79.1), (72.1, 72.7)), "b": result("b", LAPTOP_TOO, (70.0, 70.2), (72.0, 72.1))}
        (combined,) = verdict.by_class(results, "PPSA04263").values()
        self.assertEqual(combined["verdict"], "mixed")
        self.assertIn("1 faster, 1 slower", combined["text"])


class Scheduler(unittest.TestCase):
    def entry(self, machines=1):
        return {"job": formats.job_id(8104, HEAD), "pr": 8104, "head": HEAD, "priority": "normal", "titles": [], "hw": [], "machines": machines,
                "queued_by": "m", "queued_at": "2026-10-21T12:00:00Z", "earlier": [], "approval": {"by": "m", "at": "2026-10-21T12:00:00Z", "via": "label"}}

    def gap(self, results, info=LAPTOP_TOO, name="laptop-2"):
        machine = schedule.Machine(name, "tester", info, {"PPSA04263"})
        return schedule.coverage_gap(self.entry(), machine, {}, {self.entry()["job"]: results}, at("2026-10-21T13:00:00"))

    def test_borderline_class_asks_for_another_even_when_machines_is_met(self):
        value, reason = self.gap({"laptop": result("laptop", LAPTOP, (78.0, 78.0), (77.6, 77.7))})
        self.assertEqual(value, 1.0)
        self.assertIn("borderline", reason)

    def test_another_class_is_not_asked(self):
        self.assertEqual(self.gap({"laptop": result("laptop", LAPTOP, (78.0, 78.0), (77.6, 77.7))}, DESKTOP, "desktop")[0], 0.0)

    def test_settled_class_is_not_asked(self):
        self.assertEqual(self.gap({"laptop": result("laptop", LAPTOP, (79.7, 79.1), (72.1, 72.7))})[0], 0.0)

    def test_up_to_three(self):
        results = {f"m{i}": result(f"m{i}", LAPTOP, (79.7, 79.1), (72.1, 72.7)) for i in range(2)}
        results["m2"] = result("m2", LAPTOP, (78.1, 77.8), (78.2, 77.9))
        self.assertEqual(self.gap(results)[0], 0.0)


if __name__ == "__main__":
    unittest.main()


class Settings(unittest.TestCase):
    """config.json's verdicts: threshold_pct and class_max (DESIGN.md, round 4 decision 7)."""

    def test_defaults_are_1_pct_and_3(self):
        self.assertEqual(verdict.settings({}), verdict.Settings(1.0, 3))
        self.assertEqual(formats.check_config({"format": 1, "repository": "a/b", "maintainers": []})["verdicts"], {"threshold_pct": 1, "class_max": 3})

    def test_a_lower_threshold_counts_round_2s_difference(self):
        rules = verdict.settings({"verdicts": {"threshold_pct": 0.3}})
        v = verdict.machine(sides((78.0, 78.0), (77.6, 77.7)), rules)
        self.assertEqual((v["verdict"], v["borderline"]), ("faster", False))
        self.assertAlmostEqual(v["size"], 0.234)

    def test_class_max_bounds_the_borderline_ask(self):
        results = {"laptop": result("laptop", LAPTOP, (78.0, 78.0), (77.9, 78.1)), "laptop-2": result("laptop-2", LAPTOP_TOO, (78.0, 78.0), (76.0, 76.1))}
        (two,) = verdict.by_class(results, "PPSA04263").values()
        self.assertTrue(two["borderline"])  # they disagree and fewer than 3 have reported
        (capped,) = verdict.by_class(results, "PPSA04263", verdict.Settings(1.0, 2)).values()
        self.assertFalse(capped["borderline"])
        self.assertNotIn("one more machine", capped["text"])

    def test_the_scheduler_uses_class_max(self):
        entry = {"job": formats.job_id(8104, HEAD), "pr": 8104, "head": HEAD, "machines": 2, "hw": [], "titles": [], "priority": "normal",
                 "queued_at": "2026-10-21T12:00:00Z"}
        results = {entry["job"]: {"laptop": result("laptop", LAPTOP, (78.0, 78.0), (77.9, 78.1)),
                                  "laptop-2": result("laptop-2", LAPTOP_TOO, (78.0, 78.0), (76.0, 76.1))}}
        third = schedule.Machine("laptop-3", "tester", LAPTOP, {"PPSA04263"})
        self.assertEqual(schedule.coverage_gap(entry, third, {}, results, at("2026-10-21T13:00:00"))[0], 1.0)
        self.assertEqual(schedule.coverage_gap(entry, third, {}, results, at("2026-10-21T13:00:00"), verdict.Settings(1.0, 2))[0], 0.0)

    def test_bad_settings_are_refused(self):
        for bad in ({"threshold_pct": 0}, {"threshold_pct": "1"}, {"threshold_pct": 50}, {"class_max": 0}, {"class_max": 2.5}, {"class_max": True}):
            with self.assertRaises(formats.FormatError):
                formats.check_config({"format": 1, "repository": "a/b", "maintainers": [], "verdicts": bad})
