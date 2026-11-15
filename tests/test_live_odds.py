"""Offline unit tests for tjk_canli.live_odds."""
import datetime
import pathlib
from zoneinfo import ZoneInfo

import pytest

from tjk_canli.live_odds import (
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

IST_TZ = ZoneInfo("Europe/Istanbul")
FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "live_program_sample.html"


def test_parse_program_live_fixture():
    html_text = FIXTURE_PATH.read_text(encoding="utf-8")
    assert FIXTURE_PATH.stat().st_size <= 40 * 1024

    rows = parse_program_live(html_text, "2026-11-15", "İstanbul")
    assert len(rows) == 6

    assert rows[0] == {
        "race_id": "2026-11-15_İstanbul_1",
        "race_no": 1,
        "race_time": "14:00",
        "prog_no": 1,
        "ganyan_live": pytest.approx(3.45),
        "agf_pct": pytest.approx(10.2),
        "agf_rank": 4,
    }
    assert rows[1] == {
        "race_id": "2026-11-15_İstanbul_1",
        "race_no": 1,
        "race_time": "14:00",
        "prog_no": 2,
        "ganyan_live": None,
        "agf_pct": pytest.approx(19.84),
        "agf_rank": 1,
    }
    assert rows[2] == {
        "race_id": "2026-11-15_İstanbul_1",
        "race_no": 1,
        "race_time": "14:00",
        "prog_no": 3,
        "ganyan_live": pytest.approx(12.60),
        "agf_pct": pytest.approx(19.66),
        "agf_rank": 2,
    }
    assert rows[3] == {
        "race_id": "2026-11-15_İstanbul_2",
        "race_no": 2,
        "race_time": "14:30",
        "prog_no": 1,
        "ganyan_live": None,
        "agf_pct": pytest.approx(14.2),
        "agf_rank": 4,
    }
    assert rows[4] == {
        "race_id": "2026-11-15_İstanbul_2",
        "race_no": 2,
        "race_time": "14:30",
        "prog_no": 2,
        "ganyan_live": pytest.approx(7.80),
        "agf_pct": pytest.approx(2.22),
        "agf_rank": 9,
    }
    assert rows[5] == {
        "race_id": "2026-11-15_İstanbul_2",
        "race_no": 2,
        "race_time": "14:30",
        "prog_no": 4,
        "ganyan_live": pytest.approx(1.05),
        "agf_pct": pytest.approx(7.01),
        "agf_rank": 6,
    }


def test_parse_program_live_edge_cases():
    snippet = """
    <h3 class="race-no"><a id="anc900" href="#900"> 4. Koşu 15.30 </a></h3>
    <h3 class="race-no"><a id="anc901" href="#901"> 5. Koşu 16.00 </a></h3>
    <div id="kosubilgisi-999">
      <table><tbody>
        <tr class="odd">
          <td class="gunluk-GunlukYarisProgrami-SiraId">1</td>
          <td class="gunluk-GunlukYarisProgrami-Gny"><span>4.20</span></td>
          <td class="gunluk-GunlukYarisProgrami-AGFORAN"><a title="%11,5(2)">%12(2)</a></td>
        </tr>
      </tbody></table>
    </div>
    <div id="kosubilgisi-900">
      <table><tbody>
        <tr class="odd">
          <td class="gunluk-GunlukYarisProgrami-SiraId">2</td>
          <td class="gunluk-GunlukYarisProgrami-Gny"><span>Koşmaz</span></td>
          <td class="gunluk-GunlukYarisProgrami-AGFORAN">
            <a style="cursor: help;" title="1. 6'LI GANYAN : %9,58(6)">%10(6)</a>
            <a style="cursor: help;" title="2. 6'LI GANYAN : %8,54(5)"><br /> %9(5) </a>
          </td>
        </tr>
        <tr class="even">
          <td class="gunluk-GunlukYarisProgrami-SiraId">---</td>
          <td class="gunluk-GunlukYarisProgrami-Gny"><span>5.00</span></td>
          <td class="gunluk-GunlukYarisProgrami-AGFORAN"></td>
        </tr>
      </tbody></table>
    </div>
    """
    rows = parse_program_live(snippet, "2026-11-15", "İstanbul")
    assert rows == [
        {
            "race_id": "2026-11-15_İstanbul_4",
            "race_no": 4,
            "race_time": "15:30",
            "prog_no": 2,
            "ganyan_live": None,
            "agf_pct": pytest.approx(9.58),
            "agf_rank": 6,
        }
    ]
    assert parse_program_live("", "2026-11-15", "İstanbul") == []


def test_parse_cities_and_urls():
    day_html = FIXTURE_PATH.read_text(encoding="utf-8")
    assert parse_cities(day_html) == [("Adana", 1), ("İstanbul", 3)]
    assert parse_cities("<html><body>Yarış bulunamadı</body></html>") == []

    assert day_program_url("2026-11-15") == (
        "https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisProgrami"
        "?QueryParameter_Tarih=15%2F11%2F2026"
    )
    assert city_program_url("2026-11-15", "İstanbul", 3) == (
        "https://www.tjk.org/TR/YarisSever/Info/Sehir/GunlukYarisProgrami"
        "?SehirId=3&QueryParameter_Tarih=15%2F11%2F2026&SehirAdi=%C4%B0stanbul&Era=today"
    )


def test_minutes_to_post():
    now_ist = datetime.datetime(2026, 11, 15, 13, 50, 0, tzinfo=IST_TZ)
    assert minutes_to_post(now_ist, "2026-11-15", "14:00") == pytest.approx(10.0)
    assert minutes_to_post(now_ist, "2026-11-15", "14.00") == pytest.approx(10.0)

    after_ist = datetime.datetime(2026, 11, 15, 14, 5, 30, tzinfo=IST_TZ)
    assert minutes_to_post(after_ist, "2026-11-15", "14:00") == pytest.approx(-5.5)

    now_utc = datetime.datetime(2026, 11, 15, 10, 50, 0, tzinfo=datetime.timezone.utc)
    assert minutes_to_post(now_utc, "2026-11-15", "14:00") == pytest.approx(10.0)


def test_live_db_roundtrip(tmp_path):
    db_file = tmp_path / "sub" / "live_odds.db"
    conn = init_live_db(db_file)
    try:
        journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal.lower() == "wal"

        indexes = conn.execute("PRAGMA index_list('live_odds')").fetchall()
        idx_cols = [
            [r[2] for r in conn.execute(f"PRAGMA index_info('{idx[1]}')").fetchall()]
            for idx in indexes
        ]
        assert ["race_id", "captured_at"] in idx_cols

        sample_rows = [
            {
                "captured_at": "2026-11-15T13:50:00+03:00",
                "race_id": "2026-11-15_İstanbul_1",
                "prog_no": 1,
                "ganyan_live": 3.45,
                "agf_pct": 10.2,
                "agf_rank": 4,
                "race_time": "14:00",
                "minutes_to_post": 10.0,
            },
            {
                "captured_at": "2026-11-15T13:50:00+03:00",
                "race_id": "2026-11-15_İstanbul_1",
                "prog_no": 2,
                "ganyan_live": None,
                "agf_pct": 19.84,
                "agf_rank": 1,
                "race_time": "14:00",
                "minutes_to_post": 10.0,
            },
        ]
        inserted = insert_snapshots(conn, sample_rows)
        assert inserted == 2

        fetched = conn.execute(
            """
            SELECT captured_at, race_id, prog_no, ganyan_live,
                   agf_pct, agf_rank, race_time, minutes_to_post
            FROM live_odds
            ORDER BY prog_no
            """
        ).fetchall()
        assert len(fetched) == 2
        assert fetched[0] == (
            "2026-11-15T13:50:00+03:00",
            "2026-11-15_İstanbul_1",
            1,
            pytest.approx(3.45),
            pytest.approx(10.2),
            4,
            "14:00",
            pytest.approx(10.0),
        )
        assert fetched[1] == (
            "2026-11-15T13:50:00+03:00",
            "2026-11-15_İstanbul_1",
            2,
            None,
            pytest.approx(19.84),
            1,
            "14:00",
            pytest.approx(10.0),
        )
    finally:
        conn.close()


def test_parse_agf_single_quoted_title():
    snippet = """
    <h3 class="race-no"><a id="anc700" href="#700"> 1. Koşu 14.00 </a></h3>
    <div id="kosubilgisi-700"><table><tbody>
      <tr class="odd">
        <td class="gunluk-GunlukYarisProgrami-SiraId">3</td>
        <td class="gunluk-GunlukYarisProgrami-Gny"><span>4.10</span></td>
        <td class="gunluk-GunlukYarisProgrami-AGFORAN">
          <a title='1. 6"LI GANYAN : %7,25(3)'>%7(3)</a>
        </td>
      </tr>
    </tbody></table></div>
    """
    rows = parse_program_live(snippet, "2026-11-15", "İstanbul")
    assert len(rows) == 1
    assert rows[0]["agf_pct"] == pytest.approx(7.25)
    assert rows[0]["agf_rank"] == 3


def test_seconds_to_sleep():
    # Out of window (> window_min + 2): fetch_next False + capped/proportional long sleep
    sleep_sec, fetch_next = seconds_to_sleep([300.0, 330.0], 180, 60, 240.0)
    assert fetch_next is False
    assert sleep_sec == pytest.approx(1800)

    sleep_sec, fetch_next = seconds_to_sleep([250.0, 280.0], 180, 60, 240.0)
    assert fetch_next is False
    assert sleep_sec == pytest.approx(600.0)

    # Afternoon races passed (< -3), evening race still out of window
    sleep_sec, fetch_next = seconds_to_sleep([-90.0, -60.0, 260.0], 180, 60, 240.0)
    assert fetch_next is False
    assert sleep_sec == pytest.approx(1200.0)

    # In window (<= window_min + 2, > 20): fetch_next True + normal interval
    sleep_sec, fetch_next = seconds_to_sleep([242.0, 270.0], 180, 60, 240.0)
    assert fetch_next is True
    assert sleep_sec == 180

    sleep_sec, fetch_next = seconds_to_sleep([90.0, 120.0], 180, 60, 240.0)
    assert fetch_next is True
    assert sleep_sec == 180

    # Near post ([-3, 20]): fetch_next True + fast_interval
    sleep_sec, fetch_next = seconds_to_sleep([-35.0, 12.0, 42.0], 180, 60, 240.0)
    assert fetch_next is True
    assert sleep_sec == 60

    sleep_sec, fetch_next = seconds_to_sleep([-2.0, 28.0], 180, 60, 240.0)
    assert fetch_next is True
    assert sleep_sec == 60

    # Empty known_mtps: fetch_next True + normal interval
    assert seconds_to_sleep([], 180, 60, 240.0) == (180, True)


def test_should_stop():
    afternoon = datetime.datetime(2026, 11, 15, 16, 0, 0, tzinfo=IST_TZ)
    evening = datetime.datetime(2026, 11, 15, 18, 15, 0, tzinfo=IST_TZ)
    before_cutoff = datetime.datetime(2026, 11, 16, 1, 59, 0, tzinfo=IST_TZ)
    after_cutoff = datetime.datetime(2026, 11, 16, 2, 1, 0, tzinfo=IST_TZ)

    # All known races < -10 -> True
    assert should_stop([-180.0, -40.0, -10.5], evening, "2026-11-15") is True

    # Race ongoing / upcoming / boundary -10.0 -> False
    assert should_stop([-60.0, 15.0], afternoon, "2026-11-15") is False
    assert should_stop([-60.0, -10.0], evening, "2026-11-15") is False
    assert should_stop([], before_cutoff, "2026-11-15") is False

    # Next-day 02:00 Istanbul hard stop -> True regardless of known_mtps
    assert should_stop([], after_cutoff, "2026-11-15") is True
    assert should_stop([30.0], after_cutoff, "2026-11-15") is True
