"""Offline unit tests for collect.runtime_exceeded and export.export_rows."""
import csv
import datetime
import gzip
import json
import pathlib
from zoneinfo import ZoneInfo

import pytest

import collect
import export
from tjk_canli.live_odds import init_live_db, insert_snapshots

IST_TZ = ZoneInfo("Europe/Istanbul")
FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "live_program_sample.html"


def _read_gz_csv(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as gz:
        return list(csv.reader(gz))


def test_runtime_exceeded():
    assert collect.runtime_exceeded(100.0, 999999.0, None) is False
    assert collect.runtime_exceeded(100.0, 100.0 + 335.0 * 60.0 - 0.01, 335.0) is False
    assert collect.runtime_exceeded(100.0, 100.0 + 335.0 * 60.0, 335.0) is True
    assert collect.runtime_exceeded(10.0, 400.0, 5.0) is True
    assert collect.runtime_exceeded(50.0, 50.0, 0.0) is True


def test_collect_no_program_exits_zero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)
    db_file = tmp_path / "live.db"

    for fake_resp in ((200, b"<html><body>Yaris bulunamadi</body></html>"), (404, b"")):
        monkeypatch.setattr(collect, "get", lambda *a, _r=fake_resp, **kw: _r)
        rc = collect.main(["--db", str(db_file), "--date", "2026-11-15"])
        captured = capsys.readouterr().out.strip().splitlines()
        assert rc == 0
        assert len(captured) == 1
        assert not db_file.exists()


def test_collect_max_runtime_writes_last_round_and_exits_zero(tmp_path, monkeypatch):
    sample_bytes = FIXTURE_PATH.read_bytes()
    monkeypatch.setattr(collect, "_fetch_cities", lambda date_str: [("İstanbul", 3)])
    monkeypatch.setattr(collect, "get", lambda *a, **kw: (200, sample_bytes))
    monkeypatch.setattr(collect.time, "sleep", lambda s: None)

    fixed_now = datetime.datetime(2026, 11, 15, 13, 50, 0, tzinfo=IST_TZ)

    class _FakeDateTime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    monkeypatch.setattr(collect.datetime, "datetime", _FakeDateTime)

    db_file = tmp_path / "live.db"
    rc = collect.main(
        [
            "--db",
            str(db_file),
            "--date",
            "2026-11-15",
            "--max-runtime-min",
            "0",
        ]
    )
    assert rc == 0

    conn = init_live_db(db_file)
    try:
        count = conn.execute("SELECT COUNT(*) FROM live_odds").fetchone()[0]
        assert count == 6
    finally:
        conn.close()


def test_export_rows_empty_and_missing_db(tmp_path):
    out_dir = tmp_path / "veri"
    state_file = tmp_path / "state.json"

    # Non-existent DB -> writes nothing, returns [], exit 0
    assert export.export_rows(tmp_path / "missing.db", out_dir, state_file) == []
    assert not out_dir.exists()
    assert not state_file.exists()

    # Empty initialized DB -> writes nothing, returns [], state untouched
    db_file = tmp_path / "empty.db"
    conn = init_live_db(db_file)
    conn.close()

    assert export.export_rows(db_file, out_dir, state_file) == []
    assert not out_dir.exists()
    assert not state_file.exists()
    assert (
        export.main(["--db", str(db_file), "--out-dir", str(out_dir), "--state", str(state_file)])
        == 0
    )


def test_export_rows_rowid_state_gz_content_and_collision(tmp_path):
    db_file = tmp_path / "live.db"
    out_dir = tmp_path / "veri"
    state_file = tmp_path / "state.json"

    conn = init_live_db(db_file)
    try:
        insert_snapshots(
            conn,
            [
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
            ],
        )

        export_dt = datetime.datetime(2026, 11, 15, 14, 25, 3, tzinfo=IST_TZ)
        written1 = export.export_rows(db_file, out_dir, state_file, now=export_dt)
        assert written1 == [out_dir / "2026-11-15" / "142503.csv.gz"]
        assert json.loads(state_file.read_text(encoding="utf-8")) == {"last_rowid": 2}

        rows1 = _read_gz_csv(written1[0])
        assert rows1 == [
            list(export.COLUMNS),
            [
                "2026-11-15T13:50:00+03:00",
                "2026-11-15_İstanbul_1",
                "1",
                "3.45",
                "10.2",
                "4",
                "14:00",
                "10.0",
            ],
            [
                "2026-11-15T13:50:00+03:00",
                "2026-11-15_İstanbul_1",
                "2",
                "",
                "19.84",
                "1",
                "14:00",
                "10.0",
            ],
        ]

        # Calling again without new rows writes nothing
        assert export.export_rows(db_file, out_dir, state_file, now=export_dt) == []

        # Insert 3rd row and export at same HHMMSS -> -1.csv.gz, then 4th -> -2.csv.gz
        insert_snapshots(
            conn,
            [
                {
                    "captured_at": "2026-11-15T13:53:00+03:00",
                    "race_id": "2026-11-15_İstanbul_1",
                    "prog_no": 3,
                    "ganyan_live": 12.6,
                    "agf_pct": 19.66,
                    "agf_rank": 2,
                    "race_time": "14:00",
                    "minutes_to_post": 7.0,
                }
            ],
        )
        written2 = export.export_rows(db_file, out_dir, state_file, now=export_dt)
        assert written2 == [out_dir / "2026-11-15" / "142503-1.csv.gz"]
        assert json.loads(state_file.read_text(encoding="utf-8")) == {"last_rowid": 3}
        assert len(_read_gz_csv(written2[0])) == 2  # header + 1 new row

        insert_snapshots(
            conn,
            [
                {
                    "captured_at": "2026-11-15T13:56:00+03:00",
                    "race_id": "2026-11-15_İstanbul_1",
                    "prog_no": 1,
                    "ganyan_live": 3.2,
                    "agf_pct": 10.5,
                    "agf_rank": 4,
                    "race_time": "14:00",
                    "minutes_to_post": 4.0,
                }
            ],
        )
        written3 = export.export_rows(db_file, out_dir, state_file, now=export_dt)
        assert written3 == [out_dir / "2026-11-15" / "142503-2.csv.gz"]
        assert json.loads(state_file.read_text(encoding="utf-8")) == {"last_rowid": 4}
    finally:
        conn.close()


def test_export_rows_splits_by_istanbul_day(tmp_path):
    db_file = tmp_path / "live.db"
    out_dir = tmp_path / "veri"
    state_file = tmp_path / "state.json"

    conn = init_live_db(db_file)
    try:
        insert_snapshots(
            conn,
            [
                {
                    "captured_at": "2026-11-15T23:55:00+03:00",
                    "race_id": "2026-11-15_Kocaeli_8",
                    "prog_no": 1,
                    "ganyan_live": 2.5,
                    "agf_pct": 28.0,
                    "agf_rank": 1,
                    "race_time": "23:59",
                    "minutes_to_post": 4.0,
                },
                # 21:05 UTC == 00:05+03:00 on 2026-11-16 in Istanbul
                {
                    "captured_at": "2026-11-15T21:05:00+00:00",
                    "race_id": "2026-11-16_Adana_1",
                    "prog_no": 4,
                    "ganyan_live": 5.1,
                    "agf_pct": 11.0,
                    "agf_rank": 3,
                    "race_time": "13:30",
                    "minutes_to_post": 805.0,
                },
                {
                    "captured_at": "2026-11-16T00:10:00+03:00",
                    "race_id": "2026-11-16_Adana_1",
                    "prog_no": 5,
                    "ganyan_live": 8.0,
                    "agf_pct": 6.5,
                    "agf_rank": 5,
                    "race_time": "13:30",
                    "minutes_to_post": 800.0,
                },
            ],
        )
    finally:
        conn.close()

    # UTC timestamp passed as `now` -> converted to Istanbul 00:20:00
    now_utc = datetime.datetime(2026, 11, 15, 21, 20, 0, tzinfo=datetime.timezone.utc)
    written = export.export_rows(db_file, out_dir, state_file, now=now_utc)

    assert written == [
        out_dir / "2026-11-15" / "002000.csv.gz",
        out_dir / "2026-11-16" / "002000.csv.gz",
    ]
    day1_rows = _read_gz_csv(written[0])
    day2_rows = _read_gz_csv(written[1])
    assert len(day1_rows) == 2  # header + 1 row
    assert day1_rows[1][1] == "2026-11-15_Kocaeli_8"
    assert len(day2_rows) == 3  # header + 2 rows
    assert [r[2] for r in day2_rows[1:]] == ["4", "5"]


def test_export_rows_state_advances_only_after_success(tmp_path, monkeypatch):
    db_file = tmp_path / "live.db"
    out_dir = tmp_path / "veri"
    state_file = tmp_path / "state.json"
    export_dt = datetime.datetime(2026, 11, 15, 15, 0, 0, tzinfo=IST_TZ)

    conn = init_live_db(db_file)
    try:
        insert_snapshots(
            conn,
            [
                {
                    "captured_at": "2026-11-15T14:50:00+03:00",
                    "race_id": "2026-11-15_İstanbul_3",
                    "prog_no": 1,
                    "ganyan_live": 4.0,
                    "agf_pct": 15.0,
                    "agf_rank": 2,
                    "race_time": "15:00",
                    "minutes_to_post": 10.0,
                }
            ],
        )
        export.export_rows(db_file, out_dir, state_file, now=export_dt)
        assert json.loads(state_file.read_text(encoding="utf-8")) == {"last_rowid": 1}

        insert_snapshots(
            conn,
            [
                {
                    "captured_at": "2026-11-15T14:55:00+03:00",
                    "race_id": "2026-11-15_İstanbul_3",
                    "prog_no": 1,
                    "ganyan_live": 3.6,
                    "agf_pct": 16.0,
                    "agf_rank": 2,
                    "race_time": "15:00",
                    "minutes_to_post": 5.0,
                }
            ],
        )
    finally:
        conn.close()

    real_gzip_open = export.gzip.open

    def _failing_gzip_open(*args, **kwargs):
        raise OSError("simulated disk write error")

    monkeypatch.setattr(export.gzip, "open", _failing_gzip_open)
    with pytest.raises(OSError, match="simulated disk write error"):
        export.export_rows(db_file, out_dir, state_file, now=export_dt)

    # State MUST still be at rowid 1 and no -1.csv.gz or .tmp file should exist
    assert json.loads(state_file.read_text(encoding="utf-8")) == {"last_rowid": 1}
    day_files = sorted(p.name for p in (out_dir / "2026-11-15").iterdir())
    assert day_files == ["150000.csv.gz"]

    # Once write succeeds, row 2 is exported and state advances to 2
    monkeypatch.setattr(export.gzip, "open", real_gzip_open)
    written_retry = export.export_rows(db_file, out_dir, state_file, now=export_dt)
    assert written_retry == [out_dir / "2026-11-15" / "150000-1.csv.gz"]
    assert json.loads(state_file.read_text(encoding="utf-8")) == {"last_rowid": 2}
    retry_rows = _read_gz_csv(written_retry[0])
    assert len(retry_rows) == 2
    assert retry_rows[1][3] == "3.6"
