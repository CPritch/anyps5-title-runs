import unittest

from helpers import at

from title_runs import formats, schedule

NVIDIA_LINUX = formats.machine_class("NVIDIA GeForce RTX 5060 Laptop GPU", "Linux 7.2.8")
NVIDIA_LINUX_2 = formats.machine_class("NVIDIA GeForce RTX 4060", "Linux 6.17")
NVIDIA_LINUX_TWIN = formats.machine_class("NVIDIA GeForce RTX 5060 Laptop GPU", "Linux 6.17")  # the laptop's class: GPU, driver branch, OS
AMD_WINDOWS = formats.machine_class("AMD Radeon RX 6700 XT", "Windows 11")
NOW = at("2026-10-21T12:00:00")
HEAD = "69ac2e155ad018ed1fb9028d2028d15999a8571e"


def entry(pr=8104, priority="normal", titles=(), hw=(), machines=2, queued_at="2026-10-21T12:00:00Z", head=HEAD):
    return {"job": formats.job_id(pr, head), "pr": pr, "head": head, "priority": priority, "titles": list(titles), "hw": list(hw),
            "machines": machines, "queued_by": "maint", "queued_at": queued_at, "earlier": [],
            "approval": {"by": "maint", "at": queued_at, "via": "label"}, "unapproved": []}


def machine(name="laptop", info=NVIDIA_LINUX, titles=("PPSA04263",)):
    return schedule.Machine(name, "tester", info, set(titles))


def claim(job, name, info, claimed="2026-10-21T11:00:00Z", hours=3):
    return formats.make_claim(job, name, "tester", info, ["PPSA04263"], formats.parse_time(claimed), hours, head=HEAD)


def result(job, name, info, status="done"):
    return {"job": job, "machine": name, "class": info, "status": status}


class Priority(unittest.TestCase):
    def test_weights(self):
        for priority, weight in (("high", 4), ("normal", 2), ("low", 1)):
            self.assertEqual(schedule.priority_weight(entry(priority=priority))[0], weight)


class Hardware(unittest.TestCase):
    def test_empty_hw_is_half(self):
        self.assertEqual(schedule.hardware_match(entry(), machine())[0], 0.5)

    def test_vendor_os_and_family_tokens(self):
        self.assertEqual(schedule.hardware_match(entry(hw=["nvidia"]), machine())[0], 1)
        self.assertEqual(schedule.hardware_match(entry(hw=["linux"]), machine())[0], 1)
        self.assertEqual(schedule.hardware_match(entry(hw=["rtx 50"]), machine())[0], 1)
        self.assertEqual(schedule.hardware_match(entry(hw=["amd", "windows"]), machine(info=AMD_WINDOWS))[0], 1)

    def test_excluded(self):
        self.assertEqual(schedule.hardware_match(entry(hw=["amd", "intel", "windows"]), machine())[0], 0)
        self.assertEqual(schedule.hardware_match(entry(hw=["rtx 40"]), machine())[0], 0)


class Titles(unittest.TestCase):
    def test_any_title(self):
        self.assertEqual(schedule.title_match(entry(), machine())[0], 1)
        self.assertEqual(schedule.title_match(entry(), machine(titles=()))[0], 0)

    def test_wanted_title(self):
        self.assertEqual(schedule.title_match(entry(titles=["PPSA04263", "PPSA01325"]), machine())[0], 1)
        self.assertEqual(schedule.title_match(entry(titles=["PPSA01325"]), machine())[0], 0)


class Coverage(unittest.TestCase):
    def setUp(self):
        self.e = entry(machines=2)
        self.job = self.e["job"]

    def gap(self, claims=None, results=None, m=None):
        return schedule.coverage_gap(self.e, m or machine(), claims or {}, results or {}, NOW)[0]

    def test_nobody_yet(self):
        self.assertEqual(self.gap(), 1)

    def test_same_class_reported_once(self):
        self.assertEqual(self.gap(results={self.job: {"twin": result(self.job, "twin", NVIDIA_LINUX_TWIN)}}), schedule.COVERED_ONCE)

    def test_another_gpu_of_the_vendor_is_another_class(self):
        self.assertEqual(self.gap(results={self.job: {"desktop": result(self.job, "desktop", NVIDIA_LINUX_2)}}), 1)

    def test_other_class_reported(self):
        self.assertEqual(self.gap(results={self.job: {"amdbox": result(self.job, "amdbox", AMD_WINDOWS)}}), 1)

    def test_failed_result_does_not_cover(self):
        self.assertEqual(self.gap(results={self.job: {"desktop": result(self.job, "desktop", NVIDIA_LINUX_2, "failed")}}), 1)

    def test_machines_met(self):
        results = {self.job: {"desktop": result(self.job, "desktop", NVIDIA_LINUX_2), "amdbox": result(self.job, "amdbox", AMD_WINDOWS)}}
        self.assertEqual(self.gap(results=results), 0)

    def test_machines_met_with_live_claims(self):
        claims = {self.job: {"amdbox": claim(self.job, "amdbox", AMD_WINDOWS)}}
        results = {self.job: {"desktop": result(self.job, "desktop", NVIDIA_LINUX_2)}}
        self.assertEqual(self.gap(claims=claims, results=results), 0)

    def test_this_machine_reported(self):
        self.assertEqual(self.gap(results={self.job: {"laptop": result(self.job, "laptop", NVIDIA_LINUX)}}), 0)

    def test_same_class_live_claim_blocks(self):
        self.e["machines"] = 3
        self.assertEqual(self.gap(claims={self.job: {"twin": claim(self.job, "twin", NVIDIA_LINUX_TWIN)}}), 0)

    def test_another_gpu_of_the_vendor_does_not_block(self):
        self.e["machines"] = 3
        self.assertEqual(self.gap(claims={self.job: {"desktop": claim(self.job, "desktop", NVIDIA_LINUX_2)}}), 1)

    def test_other_class_live_claim_does_not_block(self):
        self.e["machines"] = 3
        self.assertEqual(self.gap(claims={self.job: {"amdbox": claim(self.job, "amdbox", AMD_WINDOWS)}}), 1)

    def test_own_claim_does_not_block(self):
        self.assertEqual(self.gap(claims={self.job: {"laptop": claim(self.job, "laptop", NVIDIA_LINUX)}}), 1)


class ExpiredClaims(unittest.TestCase):
    def test_expired_claim_counts_for_nothing(self):
        e = entry(machines=1)
        claims = {e["job"]: {"desktop": claim(e["job"], "desktop", NVIDIA_LINUX_2, claimed="2026-10-21T08:00:00Z", hours=3)}}
        self.assertTrue(formats.claim_expired(claims[e["job"]]["desktop"], NOW))
        self.assertEqual(schedule.coverage_gap(e, machine(), claims, {}, NOW)[0], 1)

    def test_claim_expiring_exactly_now_is_expired(self):
        c = claim("8104-69ac2e155ad0", "desktop", NVIDIA_LINUX_2, claimed="2026-10-21T09:00:00Z", hours=3)
        self.assertTrue(formats.claim_expired(c, NOW))

    def test_live_claim(self):
        c = claim("8104-69ac2e155ad0", "desktop", NVIDIA_LINUX_2, claimed="2026-10-21T10:00:00Z", hours=3)
        self.assertFalse(formats.claim_expired(c, NOW))


class Age(unittest.TestCase):
    def test_grows_and_caps(self):
        self.assertEqual(schedule.age(entry(queued_at="2026-10-21T12:00:00Z"), NOW)[0], 1)
        self.assertAlmostEqual(schedule.age(entry(queued_at="2026-10-20T12:00:00Z"), NOW)[0], 1.5)
        self.assertEqual(schedule.age(entry(queued_at="2026-10-01T12:00:00Z"), NOW)[0], schedule.AGE_CAP)

    def test_waiting_low_catches_up_with_fresh_normal(self):
        low = schedule.score(entry(pr=1, priority="low", queued_at="2026-10-19T12:00:00Z"), machine(), {}, {}, NOW)
        normal = schedule.score(entry(pr=2, priority="normal"), machine(), {}, {}, NOW)
        self.assertAlmostEqual(low.score, normal.score)


class Choose(unittest.TestCase):
    def test_score_is_the_product(self):
        c = schedule.score(entry(priority="high", hw=["nvidia"], titles=["PPSA04263"]), machine(), {}, {}, NOW)
        self.assertEqual(c.score, 4 * 1 * 1 * 1 * 1)
        self.assertEqual(len(c.reasons), 5)

    def test_best_first_and_zero_skipped(self):
        queue = {"entries": [entry(pr=1, priority="low"), entry(pr=2, priority="high", hw=["amd"]), entry(pr=3, priority="normal")]}
        ranked = schedule.rank(queue, machine(), {}, {}, NOW)
        self.assertEqual([c.entry["pr"] for c in ranked], [3, 1, 2])
        self.assertEqual(schedule.choose(queue, machine(), {}, {}, NOW).entry["pr"], 3)

    def test_nothing_to_do(self):
        queue = {"entries": [entry(pr=2, hw=["amd"])]}
        self.assertIsNone(schedule.choose(queue, machine(), {}, {}, NOW))

    def test_ties_go_to_the_older_entry_then_the_lower_pr(self):
        # Both ages are at the cap, so the scores are equal.
        queue = {"entries": [entry(pr=5, queued_at="2026-10-10T12:00:00Z"), entry(pr=6, queued_at="2026-10-09T12:00:00Z"),
                             entry(pr=4, queued_at="2026-10-10T12:00:00Z")]}
        ranked = schedule.rank(queue, machine(), {}, {}, NOW)
        self.assertEqual(len({c.score for c in ranked}), 1)
        self.assertEqual([c.entry["pr"] for c in ranked], [6, 4, 5])


if __name__ == "__main__":
    unittest.main()
