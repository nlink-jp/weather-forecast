#!/usr/bin/env python3
"""Behaviour tests for the bundled script (stdlib only, offline).

Every test reads recorded JMA responses under tests/fixtures/<release>/bosai/
through the script's own fetch path (a file:// base URL), so the same code
that reads the network in use reads the fixtures here.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "weather-forecast" / "scripts"
SCRIPT = SCRIPTS / "jma_forecast.py"
FIXTURES = REPO / "tests" / "fixtures"
R17 = FIXTURES / "2026-10-08T17" / "bosai"
R05 = FIXTURES / "2026-10-09T05" / "bosai"

sys.path.insert(0, str(SCRIPTS))
import jma_forecast as jf  # noqa: E402

JST = jf.JST


def at(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s).replace(tzinfo=JST)


def fetcher(root: Path = R17):
    return jf.http_fetcher(root.as_uri() + "/")


def load(root: Path, path: str):
    return json.loads((root / path).read_text(encoding="utf-8"))


AREA = load(R17, "common/const/area.json")
OFFICES = sorted(AREA["offices"])


def run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--base-url", R17.as_uri() + "/", *args],
        capture_output=True, text=True, env=env,
    )


def normalize_starts(candidate: dict, query: str) -> bool:
    return any(jf.normalize(n).startswith(query) for n in candidate["matched_names"])


class ResolveTests(unittest.TestCase):
    def names(self, query: str) -> list[tuple[str, str | None]]:
        out = jf.resolve(AREA, query)
        return [(c["office"]["code"], c["area"] and c["area"]["code"]) for c in out["candidates"]]

    def test_municipality_resolves_to_its_subdivision(self) -> None:
        self.assertEqual(self.names("札幌"), [("016000", "016010")])
        self.assertEqual(self.names("那覇"), [("471000", "471010")])

    def test_same_name_in_two_prefectures_returns_both(self) -> None:
        got = self.names("府中")
        self.assertIn(("130000", "130010"), got)
        self.assertIn(("340000", "340010"), got)
        self.assertEqual(len(got), 2)  # 府中市 and 府中町 share 340010

    def test_office_with_one_subdivision_is_that_subdivision(self) -> None:
        self.assertEqual(self.names("十勝"), [("014030", "014030")])

    def test_office_with_several_subdivisions_means_whole_region(self) -> None:
        self.assertIn(("130000", None), self.names("東京都"))

    def test_exact_match_ranks_first(self) -> None:
        # In area.json order 伊豆諸島 (Tokyo) and 東久留米市 come first.
        for query, office in (("伊豆", "220000"), ("久留米市", "400000")):
            with self.subTest(query=query):
                first = jf.resolve(AREA, query)["candidates"][0]
                self.assertTrue(first["exact"])
                self.assertEqual(first["office"]["code"], office)

    def test_contained_names_drop_out_once_a_name_starts_with_the_query(self) -> None:
        # "京都" is inside 東京都 and "大阪市" inside 東大阪市.
        self.assertNotIn("130000", [o for o, _ in self.names("京都")])
        self.assertEqual(self.names("大阪市"), [("270000", "270000")])

    def test_contained_names_remain_when_nothing_starts_with_the_query(self) -> None:
        # No name starts with 「島市」; every city ending in it stays.
        got = jf.resolve(AREA, "島市")
        self.assertGreater(got["total"], 5)
        self.assertFalse(any(normalize_starts(c, "島市") for c in got["candidates"]))

    def test_subdivision_wins_over_its_whole_office(self) -> None:
        # 「東京」 starts both 東京都 and 東京地方; 「京都」 both 京都府 and 京都市.
        self.assertEqual(self.names("東京"), [("130000", "130010")])
        self.assertEqual(self.names("京都"), [("260000", "260010")])
        # Named exactly, the whole office stays.
        self.assertEqual(self.names("東京都"), [("130000", None)])

    def test_region_name_is_not_answered_by_a_town_alone(self) -> None:
        # 東北町 (Aomori) starts with 「東北」 too; the six Tohoku offices come with it.
        got = self.names("東北")
        self.assertEqual(len(got), 7)
        for office in ("020000", "030000", "040000", "050000", "060000", "070000"):
            self.assertIn(office, [o for o, _ in got])
        self.assertIn(("380000", "380020"), self.names("四国"))  # 四国中央市 (東予)

    def test_small_ke_and_large_ke_are_the_same(self) -> None:
        for query in ("龍ヶ崎市", "龍ケ崎市", "茅ケ崎", "茅ヶ崎", "関ヶ原"):
            with self.subTest(query=query):
                self.assertEqual(jf.resolve(AREA, query)["total"], 1)

    def test_center_name_offers_its_regions(self) -> None:
        got = self.names("北海道")
        self.assertEqual(len(got), 8)
        self.assertTrue(all(o.startswith("01") for o, _ in got))

    def test_fullwidth_and_halfwidth_digits_are_the_same(self) -> None:
        self.assertEqual(jf.normalize("　ＡＢＣ１ "), "ABC1")

    def test_unknown_name_returns_no_candidates(self) -> None:
        self.assertEqual(jf.resolve(AREA, "存在しない町")["total"], 0)

    def test_empty_name_is_an_error(self) -> None:
        with self.assertRaises(jf.ForecastError) as cm:
            jf.resolve(AREA, "  ")
        self.assertEqual(cm.exception.error, "bad_query")

    def test_every_candidate_is_forecastable(self) -> None:
        # Whatever resolve hands out must be accepted by forecast.
        for q in ("府中", "東京", "奄美", "北海道", "大島"):
            for c in jf.resolve(AREA, q)["candidates"]:
                area = c["area"] and c["area"]["code"]
                jf.forecast(fetcher(), c["office"]["code"], area, at("2026-10-09T03:30"))


class AllRegionsTests(unittest.TestCase):
    """Every region and subdivision of the recorded release."""

    NOW = at("2026-10-09T03:30")

    def test_every_office(self) -> None:
        for office in OFFICES:
            with self.subTest(office=office):
                out = jf.forecast(fetcher(), office, None, self.NOW)
                children = AREA["offices"][office]["children"]
                self.assertEqual(sorted(d["area"]["code"] for d in out["detailed"]), sorted(children))
                self.assertGreaterEqual(len(out["weekly"]["rows"]), 1)
                self.assertIsNotNone(out["overview"]["text"])
                self.assertFalse(out["stale"])

    def test_every_subdivision_has_a_temperature_point(self) -> None:
        for office in OFFICES:
            for area in AREA["offices"][office]["children"]:
                with self.subTest(office=office, area=area):
                    out = jf.forecast(fetcher(), office, area, self.NOW)
                    self.assertEqual([d["area"]["code"] for d in out["detailed"]], [area])
                    self.assertIsNotNone(out["detailed"][0]["temp_point"])

    def test_every_weekly_code_in_the_data_has_a_name(self) -> None:
        # A missing name is answered with no weather word; the recorded data
        # must not hit that path, or the bundled table is out of date.
        for office in OFFICES:
            out = jf.forecast(fetcher(), office, None, self.NOW)
            for row in out["weekly"]["rows"]:
                for day in row["days"]:
                    with self.subTest(office=office, row=row["area"]["code"], date=day["date"]):
                        self.assertIsNotNone(day["weather"])


class Release05Tests(unittest.TestCase):
    """The 05:00 release of 10/9: four temperature slots, a two-day detailed
    forecast, and a weekly forecast still from 17:00 the day before."""

    NOW = at("2026-10-09T09:55")

    def test_every_office_and_subdivision(self) -> None:
        for office in OFFICES:
            for area in AREA["offices"][office]["children"]:
                with self.subTest(office=office, area=area):
                    out = jf.forecast(fetcher(R05), office, area, self.NOW)
                    self.assertIsNotNone(out["detailed"][0]["temp_point"])
                    self.assertGreaterEqual(len(out["weekly"]["rows"]), 1)

    def test_today_has_no_morning_low(self) -> None:
        # Raw temps for 東京: today 09:00 = 26, today 00:00 = 26 (the 24-hour
        # maximum, identical on all 171 points), tomorrow 00:00 = 16, 09:00 = 25.
        out = jf.forecast(fetcher(R05), "130000", "130010", self.NOW)
        days = {d["date"]: d for d in out["detailed"][0]["days"]}
        self.assertEqual((days["2026-10-09"]["temp_min"], days["2026-10-09"]["temp_max"]), (None, 26))
        self.assertEqual((days["2026-10-10"]["temp_min"], days["2026-10-10"]["temp_max"]), (16, 25))

    def test_two_day_detailed_forecast(self) -> None:
        out = jf.forecast(fetcher(R05), "130000", "130010", self.NOW)
        self.assertEqual([d["label"] for d in out["detailed"][0]["days"]], ["今日", "明日"])

    def test_old_weekly_release_does_not_make_it_stale(self) -> None:
        out = jf.forecast(fetcher(R05), "130000", None, self.NOW)
        self.assertEqual(out["weekly"]["report_datetime"], "2026-10-08T17:00:00+09:00")
        self.assertFalse(out["stale"])


class SharedFileTests(unittest.TestCase):
    NOW = at("2026-10-09T03:30")

    def test_tokachi_reads_kushiro_file_and_keeps_only_tokachi(self) -> None:
        out = jf.forecast(fetcher(), "014030", "014030", self.NOW)
        self.assertEqual([d["area"]["name"] for d in out["detailed"]], ["十勝地方"])
        rows = out["weekly"]["rows"]
        self.assertEqual([r["area"]["code"] for r in rows], ["014000"])
        self.assertTrue(rows[0]["matched"])

    def test_amami_gets_only_its_weekly_row(self) -> None:
        out = jf.forecast(fetcher(), "460040", None, self.NOW)
        self.assertEqual([r["area"]["name"] for r in out["weekly"]["rows"]], ["奄美地方"])

    def test_kagoshima_excludes_amami_weekly_row(self) -> None:
        out = jf.forecast(fetcher(), "460100", None, self.NOW)
        self.assertEqual([r["area"]["code"] for r in out["weekly"]["rows"]], ["460100"])

    def test_shared_offices_have_no_file_of_their_own(self) -> None:
        for office in jf.SHARED_FILE:
            self.assertFalse((R17 / f"forecast/data/forecast/{office}.json").exists())


class WeeklyMatchTests(unittest.TestCase):
    NOW = at("2026-10-09T03:30")

    def test_tokyo_lists_all_three_rows_like_the_official_page(self) -> None:
        out = jf.forecast(fetcher(), "130000", None, self.NOW)
        self.assertEqual([r["area"]["name"] for r in out["weekly"]["rows"]],
                         ["東京地方", "伊豆諸島", "小笠原諸島"])
        self.assertEqual([r["temp_point"] for r in out["weekly"]["rows"]], ["東京", "八丈島", "父島"])

    def test_match_is_marked_only_when_a_candidate_is_present(self) -> None:
        tokyo = jf.forecast(fetcher(), "130000", "130010", self.NOW)
        self.assertEqual([r["matched"] for r in tokyo["weekly"]["rows"]], [True, False, False])
        hachijo = jf.forecast(fetcher(), "130000", "130030", self.NOW)
        self.assertEqual([r["matched"] for r in hachijo["weekly"]["rows"]], [False, True, False])
        # 伊豆諸島北部 has no candidate in today's data: nothing is guessed.
        oshima = jf.forecast(fetcher(), "130000", "130020", self.NOW)
        self.assertEqual([r["matched"] for r in oshima["weekly"]["rows"]], [False, False, False])

    def test_blank_values_become_null_and_ranges_pair_up(self) -> None:
        out = jf.forecast(fetcher(), "130000", "130010", at("2026-10-08T18:00"))
        first, second, third = out["weekly"]["rows"][0]["days"][:3]
        self.assertEqual(first["date"], "2026-10-09")
        self.assertIsNone(first["pop"])
        self.assertIsNone(first["temp_max"])
        self.assertIsNone(first["temp_max_range"])
        self.assertIsNone(second["reliability"])
        self.assertEqual(third["reliability"], "A")
        self.assertEqual(third["temp_max_range"], [25, 29])


class DateTests(unittest.TestCase):
    """The 17:00 release, read in the evening and after midnight."""

    def days(self, now: str) -> list[tuple[str, str | None]]:
        out = jf.forecast(fetcher(), "130000", "130010", at(now))
        return [(d["date"], d["label"]) for d in out["detailed"][0]["days"]]

    def test_evening_of_release_day(self) -> None:
        self.assertEqual(self.days("2026-10-08T18:00"),
                         [("2026-10-08", "今日"), ("2026-10-09", "明日"), ("2026-10-10", "明後日")])

    def test_after_midnight_drops_yesterday_and_relabels(self) -> None:
        self.assertEqual(self.days("2026-10-09T03:30"),
                         [("2026-10-09", "今日"), ("2026-10-10", "明日")])

    def test_midnight_boundary(self) -> None:
        self.assertEqual(self.days("2026-10-08T23:59")[0], ("2026-10-08", "今日"))
        self.assertEqual(self.days("2026-10-09T00:00")[0], ("2026-10-09", "今日"))

    def test_weekday_is_given_for_every_day(self) -> None:
        out = jf.forecast(fetcher(), "130000", "130010", at("2026-10-09T03:30"))
        self.assertEqual(out["detailed"][0]["days"][0]["weekday"], "金")  # 2026-10-09
        weekly = out["weekly"]["rows"][0]["days"]
        self.assertEqual([d["weekday"] for d in weekly], list("金土日月火水木"))

    def test_weekly_drops_past_days_too(self) -> None:
        out = jf.forecast(fetcher(), "130000", None, at("2026-10-11T12:00"))
        days = out["weekly"]["rows"][0]["days"]
        self.assertEqual((days[0]["date"], days[0]["label"], days[0]["weekday"]), ("2026-10-11", "今日", "日"))
        self.assertEqual(len(days), 5)

    def test_now_in_another_offset_is_read_as_jst(self) -> None:
        # 2026-10-08T15:30Z is 00:30 JST on the 9th — passed in UTC as it is.
        now = dt.datetime(2026, 10, 8, 15, 30, tzinfo=dt.timezone.utc)
        out = jf.forecast(fetcher(), "130000", "130010", now)
        self.assertEqual(out["detailed"][0]["days"][0]["date"], "2026-10-09")

    def test_cli_now_offsets(self) -> None:
        # Run in a UTC host zone: a time without an offset must still be JST.
        env = {**os.environ, "TZ": "UTC"}
        for now in ("2026-10-08T15:30+00:00", "2026-10-09T00:30"):  # the latter has no offset
            with self.subTest(now=now):
                proc = run("--now", now, "forecast", "--office", "130000", "--area", "130010", env=env)
                out = json.loads(proc.stdout)
                self.assertEqual(out["now"], "2026-10-09T00:30+09:00")
                self.assertEqual(out["detailed"][0]["days"][0]["date"], "2026-10-09")


class PopSlotTests(unittest.TestCase):
    """6-hour precipitation slots: a slot ending exactly now is over."""

    def slots(self, now: str) -> list[tuple[str, str, str]]:
        out = jf.forecast(fetcher(), "130000", "130010", at(now))
        return [(d["date"], p["from"], p["to"]) for d in out["detailed"][0]["days"] for p in d["pops"]]

    def test_boundaries_at_several_phases(self) -> None:
        cases = {
            "2026-10-09T05:59": ("2026-10-09", "00:00", "06:00"),
            "2026-10-09T06:00": ("2026-10-09", "06:00", "12:00"),
            "2026-10-09T06:01": ("2026-10-09", "06:00", "12:00"),
            "2026-10-09T11:59": ("2026-10-09", "06:00", "12:00"),
            "2026-10-09T12:00": ("2026-10-09", "12:00", "18:00"),
            "2026-10-09T17:59": ("2026-10-09", "12:00", "18:00"),
            "2026-10-09T18:00": ("2026-10-09", "18:00", "24:00"),
        }
        for now, first in cases.items():
            with self.subTest(now=now):
                self.assertEqual(self.slots(now)[0], first)

    def test_last_slot_runs_to_midnight(self) -> None:
        self.assertEqual(self.slots("2026-10-08T18:00")[0], ("2026-10-08", "18:00", "24:00"))

    def test_no_slot_left_after_last_one_ends(self) -> None:
        self.assertEqual(self.slots("2026-10-10T00:00"), [])


class FreshnessTests(unittest.TestCase):
    def stale(self, now: str) -> bool:
        return jf.forecast(fetcher(), "130000", None, at(now))["stale"]

    def test_threshold(self) -> None:
        self.assertFalse(self.stale("2026-10-09T08:00"))  # report + 15h exactly
        self.assertTrue(self.stale("2026-10-09T08:01"))


class TemperatureSlotTests(unittest.TestCase):
    """The four documented slots (府県天気予報 解説資料 ※2)."""

    def test_four_slots(self) -> None:
        times = [at("2026-10-09T00:00"), at("2026-10-09T09:00"),
                 at("2026-10-10T00:00"), at("2026-10-10T09:00")]
        self.assertEqual(jf.temp_slots(times), [
            None,        # 今日 (24 h): 最高気温, not a low
            "temp_max",  # 今日日中: 日中の最高気温
            "temp_min",  # 明日朝: 朝の最低気温
            "temp_max",  # 明日日中
        ])

    def test_four_slots_in_any_order(self) -> None:
        times = [at("2026-10-09T09:00"), at("2026-10-09T00:00"),
                 at("2026-10-10T00:00"), at("2026-10-10T09:00")]
        self.assertEqual(jf.temp_slots(times), ["temp_max", None, "temp_min", "temp_max"])

    def test_two_slots(self) -> None:
        # 17:00 and 20:00 releases, and a correction issued after midnight.
        times = [at("2026-10-09T00:00"), at("2026-10-09T09:00")]
        self.assertEqual(jf.temp_slots(times), ["temp_min", "temp_max"])


class TemperatureTests(unittest.TestCase):
    def test_17_release_gives_tomorrow_min_and_max(self) -> None:
        # Official page (17:00 release of 10/8): 東京 明日 朝の最低 15, 日中の最高 26.
        out = jf.forecast(fetcher(), "130000", "130010", at("2026-10-08T18:00"))
        days = {d["date"]: d for d in out["detailed"][0]["days"]}
        self.assertEqual((days["2026-10-09"]["temp_min"], days["2026-10-09"]["temp_max"]), (15, 26))
        self.assertEqual((days["2026-10-08"]["temp_min"], days["2026-10-08"]["temp_max"]), (None, None))

    def test_first_present_point_wins(self) -> None:
        # forecast_area.json lists 73136 first for 愛媛県東予 although today's
        # data carries no such point; the next listed one (新居浜) is used.
        fa = load(R17, "forecast/const/forecast_area.json")
        listed = next(e["amedas"] for e in fa["380000"] if e["class10"] == "380020")
        self.assertEqual(listed[0], "73136")
        out = jf.forecast(fetcher(), "380000", "380020", at("2026-10-09T03:30"))
        self.assertEqual(out["detailed"][0]["temp_point"], "新居浜")

    def test_landlocked_prefecture_has_no_waves(self) -> None:
        out = jf.forecast(fetcher(), "090000", None, at("2026-10-09T03:30"))  # 栃木県
        self.assertTrue(all(d["wave"] is None for a in out["detailed"] for d in a["days"]))


class TextTests(unittest.TestCase):
    def test_tidy_collapses_ideographic_spaces(self) -> None:
        self.assertEqual(jf.tidy("晴れ　時々　くもり"), "晴れ 時々 くもり")
        self.assertIsNone(jf.tidy(None))

    def test_unknown_telop_has_no_name(self) -> None:
        self.assertIsNone(jf.telop_name("199"))
        self.assertIsNone(jf.telop_name(None))

    def test_documented_name_wins_over_the_page(self) -> None:
        # Documented table: 晴れ時々くもり; forecast page: 晴時々曇.
        self.assertEqual(jf.telop_name("101"), "晴れ時々くもり")

    def test_page_names_numbers_the_document_no_longer_lists(self) -> None:
        self.assertEqual(jf.telop_name("108"), "晴一時雨か雷雨")

    def test_every_documented_number_is_also_on_the_page(self) -> None:
        tables = json.loads((SCRIPTS / "telops.json").read_text(encoding="utf-8"))
        self.assertEqual(len(tables["official"]["telops"]), 66)
        self.assertLessEqual(set(tables["official"]["telops"]), set(tables["page"]["telops"]))

    def test_answer_fields_carry_no_telop_number(self) -> None:
        out = jf.forecast(fetcher(), "130000", None, at("2026-10-09T03:30"))
        for row in out["weekly"]["rows"]:
            for day in row["days"]:
                self.assertIsNone(re.fullmatch(r"\d{3}", day["weather"] or ""))

    def test_attribution_names_source_and_processing(self) -> None:
        out = jf.forecast(fetcher(), "130000", None, at("2026-10-09T03:30"))
        self.assertIn("気象庁ホームページ", out["attribution"])
        self.assertIn("area_code=130000", out["attribution"])
        self.assertIn("加工して作成", out["attribution"])


class CliTests(unittest.TestCase):
    def test_forecast_prints_json(self) -> None:
        proc = run("--now", "2026-10-09T03:30+09:00", "forecast", "--office", "130000")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["office"]["name"], "東京都")

    def test_resolve_prints_json(self) -> None:
        proc = run("resolve", "札幌")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["total"], 1)

    def test_errors_are_json_with_exit_2(self) -> None:
        cases = {
            ("forecast", "--office", "999999"): "unknown_office",
            ("forecast", "--office", "130000", "--area", "270000"): "unknown_area",
        }
        for args, error in cases.items():
            with self.subTest(args=args):
                proc = run(*args)
                self.assertEqual(proc.returncode, 2)
                self.assertEqual(json.loads(proc.stdout)["error"], error)

    def broken_copy(self, tmp: str, path: str, content: bytes) -> str:
        root = Path(tmp) / "bosai"
        shutil.copytree(R17, root)
        (root / path).write_bytes(content)
        return root.as_uri() + "/"

    def test_malformed_data_is_bad_response_not_a_traceback(self) -> None:
        cases = {
            "forecast/data/forecast/130000.json": b"[]",
            "forecast/data/overview_forecast/130000.json": "概況".encode("shift_jis"),
        }
        for path, content in cases.items():
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                base = self.broken_copy(tmp, path, content)
                proc = subprocess.run(
                    [sys.executable, "-I", str(SCRIPT), "--base-url", base,
                     "forecast", "--office", "130000"],
                    capture_output=True, text=True,
                )
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["error"], "bad_response")
                self.assertNotIn("Traceback", proc.stderr)

    def test_weekly_rows_that_do_not_pair_up_fail(self) -> None:
        data = load(R17, "forecast/data/forecast/130000.json")
        data[1]["timeSeries"][1]["areas"].pop()
        with self.assertRaises(jf.ForecastError) as cm:
            jf.build_weekly(data[1], [], None, at("2026-10-09T03:30"))
        self.assertEqual(cm.exception.error, "bad_response")

    def test_unparsable_now_is_json_too(self) -> None:
        proc = run("--now", "tomorrow", "resolve", "札幌")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", json.loads(proc.stdout))

    def test_unreachable_source_is_fetch_failed(self) -> None:
        with tempfile.TemporaryDirectory() as empty:
            proc = subprocess.run(
                [sys.executable, "-I", str(SCRIPT), "--base-url", Path(empty).as_uri() + "/",
                 "resolve", "札幌"],
                capture_output=True, text=True,
            )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(json.loads(proc.stdout)["error"], "fetch_failed")

    def test_default_source_is_jma(self) -> None:
        self.assertEqual(jf.BASE_URL, "https://www.jma.go.jp/bosai/")


if __name__ == "__main__":
    unittest.main(verbosity=1)
