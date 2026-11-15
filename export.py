"""Incremental SQLite-to-CSV.gz exporter partitioned by Istanbul calendar day."""
import argparse
import collections
import csv
import datetime
import gzip
import json
import os
import pathlib
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tjk_canli.live_odds import IST_TZ

COLUMNS = (
    "captured_at",
    "race_id",
    "prog_no",
    "ganyan_live",
    "agf_pct",
    "agf_rank",
    "race_time",
    "minutes_to_post",
)


def _istanbul_day(captured_at):
    raw = str(captured_at).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST_TZ)
    else:
        dt = dt.astimezone(IST_TZ)
    return dt.date().isoformat()


def _export_hms(now):
    if now is None:
        now_ist = datetime.datetime.now(IST_TZ)
    elif now.tzinfo is None:
        now_ist = now.replace(tzinfo=IST_TZ)
    else:
        now_ist = now.astimezone(IST_TZ)
    return now_ist.strftime("%H%M%S")


def _next_available_path(day_dir, hms):
    candidate = day_dir / f"{hms}.csv.gz"
    if not candidate.exists():
        return candidate
    idx = 1
    while True:
        candidate = day_dir / f"{hms}-{idx}.csv.gz"
        if not candidate.exists():
            return candidate
        idx += 1


def _read_last_rowid(state_path):
    p = pathlib.Path(state_path)
    if not p.exists():
        return 0
    data = json.loads(p.read_text(encoding="utf-8"))
    return int(data.get("last_rowid", 0))


def _write_last_rowid(state_path, last_rowid):
    state_p = pathlib.Path(state_path)
    state_p.parent.mkdir(parents=True, exist_ok=True)
    tmp_state = state_p.with_name(f".{state_p.name}.tmp")
    try:
        tmp_state.write_text(
            json.dumps({"last_rowid": int(last_rowid)}) + "\n",
            encoding="utf-8",
        )
        os.replace(tmp_state, state_p)
    except BaseException:
        try:
            tmp_state.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def export_rows(db_path, out_dir="veri", state_path="/tmp/export_state.json", now=None):
    """Export rows with rowid > state.last_rowid into <out_dir>/<YYYY-MM-DD>/<HHMMSS>.csv.gz."""
    last_rowid = _read_last_rowid(state_path)

    db_str = str(db_path)
    if db_str != ":memory:" and not pathlib.Path(db_path).exists():
        return []

    conn = sqlite3.connect(db_str, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        has_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='live_odds'"
        ).fetchone()
        if has_table is None:
            return []
        rows = conn.execute(
            """
            SELECT rowid, captured_at, race_id, prog_no, ganyan_live,
                   agf_pct, agf_rank, race_time, minutes_to_post
            FROM live_odds
            WHERE rowid > ?
            ORDER BY rowid ASC
            """,
            (last_rowid,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return []

    max_rowid = rows[-1][0]
    by_day = collections.defaultdict(list)
    for row in rows:
        day_str = _istanbul_day(row[1])
        by_day[day_str].append(row[1:])

    hms = _export_hms(now)
    out_root = pathlib.Path(out_dir)
    staged = []

    try:
        for day_str in sorted(by_day):
            day_dir = out_root / day_str
            day_dir.mkdir(parents=True, exist_ok=True)
            target = _next_available_path(day_dir, hms)
            tmp_target = day_dir / f".{target.name}.tmp"
            staged.append((tmp_target, target))
            with gzip.open(tmp_target, "wt", encoding="utf-8", newline="") as gz:
                writer = csv.writer(gz, lineterminator="\n")
                writer.writerow(COLUMNS)
                writer.writerows(by_day[day_str])

        written = []
        for tmp_target, target in staged:
            os.replace(tmp_target, target)
            written.append(target)
    except BaseException:
        for tmp_target, _ in staged:
            try:
                tmp_target.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    _write_last_rowid(state_path, max_rowid)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(description="Export new live_odds rows to daily CSV.gz files.")
    ap.add_argument("--db", required=True, help="Source SQLite database path")
    ap.add_argument("--out-dir", default="veri", help="Output root directory (default: veri)")
    ap.add_argument(
        "--state",
        default="/tmp/export_state.json",
        help="State file tracking last exported rowid",
    )
    args = ap.parse_args(argv)

    written = export_rows(args.db, out_dir=args.out_dir, state_path=args.state)
    for path in written:
        print(f"dışa aktarıldı: {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
