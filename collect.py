"""Standalone race-day live Ganyan odds & AGF collector (writes only to its own SQLite DB)."""
import argparse
import datetime
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tjk_canli.http import DELAY, get
from tjk_canli.live_odds import (
    IST_TZ,
    city_program_url,
    day_program_url,
    init_live_db,
    insert_snapshots,
    minutes_to_post,
    parse_cities,
    parse_program_live,
    seconds_to_sleep,
    should_stop,
)

XHR_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
CITY_REFRESH_SEC = 1800


def runtime_exceeded(start_monotonic, now_monotonic, max_min):
    """Return True when max_min is set and elapsed monotonic time reached it."""
    if max_min is None:
        return False
    return (now_monotonic - start_monotonic) >= max_min * 60.0


def _fetch_cities(date_str):
    st, body = get(day_program_url(date_str), tries=2, timeout=15)
    time.sleep(DELAY)
    if st == 404:
        return []
    if st != 200 or not body:
        raise RuntimeError(f"gün sayfası alınamadı (HTTP {st}, {len(body)} B)")
    return parse_cities(body.decode("utf-8", "replace"))


def _format_next_race(known_races, now_dt, date_str):
    if not known_races:
        return "sıradaki koşu yok"
    scored = [
        (minutes_to_post(now_dt, date_str, rt), city, race_no)
        for (city, race_no), rt in known_races.items()
    ]
    upcoming = [x for x in scored if x[0] >= -3.0]
    mtp, city, race_no = min(upcoming) if upcoming else max(scored)
    return f"sıradaki koşu {city} {race_no}. {mtp:+.0f} dk"


def _cap_sleep(sleep_sec, start_mono, now_mono, max_min):
    if max_min is None:
        return sleep_sec
    remaining = max_min * 60.0 - (now_mono - start_mono)
    return max(0.0, min(sleep_sec, remaining))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Collect live TJK Ganyan odds and AGF snapshots.")
    ap.add_argument("--db", default="live_odds.db", help="Target SQLite path")
    ap.add_argument("--date", default=None, help="Race date YYYY-MM-DD (default: today in Istanbul)")
    ap.add_argument("--once", action="store_true", help="Run a single collection pass and exit")
    ap.add_argument("--interval", type=int, default=180, help="Normal polling interval in seconds")
    ap.add_argument("--fast-interval", type=int, default=60, help="Near-post polling interval in seconds")
    ap.add_argument("--window-min", type=float, default=240.0, help="Capture races within this many minutes")
    ap.add_argument(
        "--max-runtime-min",
        type=float,
        default=None,
        help="Maximum runtime in minutes before clean exit (default: unlimited)",
    )
    args = ap.parse_args(argv)

    start_mono = time.monotonic()
    date_str = args.date or datetime.datetime.now(IST_TZ).date().isoformat()

    try:
        cities = _fetch_cities(date_str)
    except Exception as exc:
        now_hms = datetime.datetime.now(IST_TZ).strftime("%H:%M:%S")
        print(f"[{now_hms}] başlangıç hatası ({date_str}): {exc}", flush=True)
        return 1

    if not cities:
        now_hms = datetime.datetime.now(IST_TZ).strftime("%H:%M:%S")
        print(f"[{now_hms}] {date_str}: bugün yarış programı yok", flush=True)
        return 0

    conn = init_live_db(args.db)
    last_city_refresh = time.monotonic()
    known_races = {}
    first_round = True

    try:
        while True:
            if not first_round:
                now_dt = datetime.datetime.now(IST_TZ)
                now_mono = time.monotonic()
                if runtime_exceeded(start_mono, now_mono, args.max_runtime_min):
                    hms = now_dt.strftime("%H:%M:%S")
                    print(f"[{hms}] çalışma süresi doldu ({args.max_runtime_min:g} dk)", flush=True)
                    return 0
                all_mtps = [
                    minutes_to_post(now_dt, date_str, rt)
                    for rt in known_races.values()
                ]
                if should_stop(all_mtps, now_dt, date_str):
                    return 0
                sleep_sec, fetch_next = seconds_to_sleep(
                    all_mtps, args.interval, args.fast_interval, args.window_min
                )
                if not fetch_next:
                    sleep_sec = _cap_sleep(sleep_sec, start_mono, now_mono, args.max_runtime_min)
                    hms = now_dt.strftime("%H:%M:%S")
                    next_info = _format_next_race(known_races, now_dt, date_str)
                    sleep_min = max(1, round(sleep_sec / 60))
                    print(
                        f"[{hms}] pencere dışı: {next_info}; {sleep_min} dk uyunuyor",
                        flush=True,
                    )
                    time.sleep(sleep_sec)
                    continue
            first_round = False

            if time.monotonic() - last_city_refresh >= CITY_REFRESH_SEC:
                try:
                    refreshed = _fetch_cities(date_str)
                    if refreshed:
                        merged = dict(cities)
                        for c_name, c_id in refreshed:
                            merged[c_name] = c_id
                        cities = list(merged.items())
                except Exception as exc:
                    now_hms = datetime.datetime.now(IST_TZ).strftime("%H:%M:%S")
                    print(f"[{now_hms}] şehir yenileme hatası: {exc}", flush=True)
                last_city_refresh = time.monotonic()

            city_summaries = []

            for idx, (city, sehir_id) in enumerate(cities):
                if idx > 0:
                    time.sleep(DELAY)
                try:
                    url = city_program_url(date_str, city, sehir_id)
                    st, body = get(url, tries=2, timeout=20, extra_headers=XHR_HEADERS)
                    if st != 200 or not body:
                        raise RuntimeError(f"HTTP {st}, {len(body)} B")

                    parsed = parse_program_live(body.decode("utf-8", "replace"), date_str, city)
                    if not parsed:
                        raise RuntimeError("0 satır ayrıştırıldı")

                    now_dt = datetime.datetime.now(IST_TZ)
                    captured_at = now_dt.isoformat(timespec="seconds")

                    for r in parsed:
                        known_races[(city, r["race_no"])] = r["race_time"]

                    to_insert = []
                    for r in parsed:
                        mtp = minutes_to_post(now_dt, date_str, r["race_time"])
                        if -3.0 < mtp <= args.window_min and (
                            r["ganyan_live"] is not None or r["agf_pct"] is not None
                        ):
                            to_insert.append({
                                "captured_at": captured_at,
                                "race_id": r["race_id"],
                                "prog_no": r["prog_no"],
                                "ganyan_live": r["ganyan_live"],
                                "agf_pct": r["agf_pct"],
                                "agf_rank": r["agf_rank"],
                                "race_time": r["race_time"],
                                "minutes_to_post": round(mtp, 2),
                            })

                    if to_insert:
                        insert_snapshots(conn, to_insert)

                    n_rows = len(to_insert)
                    n_live = sum(1 for r in to_insert if r["ganyan_live"] is not None)
                    city_summaries.append(f"{city}: {n_rows} satır, {n_live} canlı oranlı")
                except Exception as exc:
                    city_summaries.append(f"{city}: hata ({exc})")

            round_end_dt = datetime.datetime.now(IST_TZ)
            hms = round_end_dt.strftime("%H:%M:%S")
            next_info = _format_next_race(known_races, round_end_dt, date_str)
            print(f"[{hms}] {'; '.join(city_summaries)} | {next_info}", flush=True)

            if args.once:
                return 0

            now_mono = time.monotonic()
            if runtime_exceeded(start_mono, now_mono, args.max_runtime_min):
                print(f"[{hms}] çalışma süresi doldu ({args.max_runtime_min:g} dk)", flush=True)
                return 0

            all_mtps = [
                minutes_to_post(round_end_dt, date_str, rt)
                for rt in known_races.values()
            ]
            if should_stop(all_mtps, round_end_dt, date_str):
                return 0

            sleep_sec, fetch_next = seconds_to_sleep(
                all_mtps, args.interval, args.fast_interval, args.window_min
            )
            if fetch_next:
                sleep_sec = _cap_sleep(sleep_sec, start_mono, now_mono, args.max_runtime_min)
                time.sleep(sleep_sec)
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
