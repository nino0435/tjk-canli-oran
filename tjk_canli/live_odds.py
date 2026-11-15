"""Live Ganyan odds and AGF HTML parser, URL builders, and SQLite helpers."""
import datetime
import html
import os
import re
import sqlite3
import urllib.parse
from zoneinfo import ZoneInfo

IST_TZ = ZoneInfo("Europe/Istanbul")

_TAG_RE = re.compile(r"<[^>]+>")
_TAB_ANCHOR_RE = re.compile(
    r'<a\b[^>]*\bid=["\']anc(\d+)["\'][^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_TAB_TEXT_RE = re.compile(r"(\d+)\.\s*Koşu\s+(\d{1,2})[.:](\d{2})", re.IGNORECASE)
_BODY_START_RE = re.compile(r'\bid=["\']kosubilgisi-(\d+)["\']', re.IGNORECASE)
_END_TABLE_RE = re.compile(r"</table>", re.IGNORECASE)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TITLE_ATTR_RE = re.compile(r"""\btitle=(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
_AGF_VAL_RE = re.compile(r"%\s*(\d+(?:[.,]\d+)?)\s*\(\s*(\d+)\s*\)")
_NUM_TOKEN_RE = re.compile(r"^\d+(?:[.,]\d+)?$")
_CITY_ANCHOR_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.DOTALL | re.IGNORECASE)
_ATTR_ID_RE = re.compile(r'\bid=["\']([^"\']+)["\']', re.IGNORECASE)
_ATTR_SEHIR_ID_RE = re.compile(r'\bdata-sehir-id=["\'](\d+)["\']', re.IGNORECASE)

_CELL_RES = {
    col: re.compile(
        rf'<td\b[^>]*\bgunluk-GunlukYarisProgrami-{col}\b[^>]*>(.*?)</td>',
        re.DOTALL | re.IGNORECASE,
    )
    for col in ("SiraId", "Gny", "AGFORAN")
}


def num(s):
    s = (s or "").strip().replace(",", ".")
    m = re.match(r"^-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def _strip_tags(fragment):
    return _TAG_RE.sub("", fragment or "")


def _parse_gny(cell_html):
    if cell_html is None:
        return None
    txt = html.unescape(_strip_tags(cell_html)).strip()
    if not _NUM_TOKEN_RE.match(txt):
        return None
    val = num(txt)
    if val is None or val <= 0 or abs(val - 999.99) < 1e-6:
        return None
    return val


def _parse_agf(cell_html):
    if cell_html is None:
        return None, None
    match = None
    for tm in _TITLE_ATTR_RE.finditer(cell_html):
        raw_title = tm.group(1) if tm.group(1) is not None else tm.group(2)
        match = _AGF_VAL_RE.search(html.unescape(raw_title))
        if match:
            break
    if match is None:
        match = _AGF_VAL_RE.search(html.unescape(_strip_tags(cell_html)))
    if match is None:
        return None, None
    pct = num(match.group(1))
    if pct is None:
        return None, None
    return pct, int(match.group(2))


def parse_program_live(html_text, date_str, city):
    """Parse TJK city program HTML into per-runner live odds and AGF dicts."""
    if not html_text:
        return []

    race_map = {}
    for m in _TAB_ANCHOR_RE.finditer(html_text):
        kosu_id = m.group(1)
        txt = html.unescape(_strip_tags(m.group(2)))
        tm = _TAB_TEXT_RE.search(txt)
        if not tm:
            continue
        race_no = int(tm.group(1))
        hh, mm = int(tm.group(2)), int(tm.group(3))
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            continue
        race_map[kosu_id] = (race_no, f"{hh:02d}:{mm:02d}")

    if not race_map:
        return []

    rows_out = []
    body_matches = list(_BODY_START_RE.finditer(html_text))
    for idx, bm in enumerate(body_matches):
        kosu_id = bm.group(1)
        if kosu_id not in race_map:
            continue
        race_no, race_time = race_map[kosu_id]
        race_id = f"{date_str}_{city}_{race_no}"

        start = bm.end()
        end = body_matches[idx + 1].start() if idx + 1 < len(body_matches) else len(html_text)
        section = html_text[start:end]
        end_tbl = _END_TABLE_RE.search(section)
        if end_tbl:
            section = section[: end_tbl.start()]

        for rm in _ROW_RE.finditer(section):
            row_html = rm.group(1)
            sira_m = _CELL_RES["SiraId"].search(row_html)
            if not sira_m:
                continue
            sira_txt = html.unescape(_strip_tags(sira_m.group(1))).strip()
            if not sira_txt.isdigit():
                continue
            prog_no = int(sira_txt)
            if prog_no <= 0:
                continue

            gny_m = _CELL_RES["Gny"].search(row_html)
            agf_m = _CELL_RES["AGFORAN"].search(row_html)
            ganyan_live = _parse_gny(gny_m.group(1) if gny_m else None)
            agf_pct, agf_rank = _parse_agf(agf_m.group(1) if agf_m else None)

            rows_out.append({
                "race_id": race_id,
                "race_no": race_no,
                "race_time": race_time,
                "prog_no": prog_no,
                "ganyan_live": ganyan_live,
                "agf_pct": agf_pct,
                "agf_rank": agf_rank,
            })

    return rows_out


def parse_cities(day_html):
    """Extract ordered, deduplicated domestic (city, sehir_id) pairs from TJK day page."""
    if not day_html:
        return []
    seen = set()
    cities = []
    for m in _CITY_ANCHOR_RE.finditer(day_html):
        attrs, inner = m.group(1), m.group(2)
        if "Y.G." not in html.unescape(_strip_tags(inner)):
            continue
        id_m = _ATTR_ID_RE.search(attrs)
        sid_m = _ATTR_SEHIR_ID_RE.search(attrs)
        if not id_m or not sid_m:
            continue
        name = html.unescape(id_m.group(1)).strip()
        sehir_id = int(sid_m.group(1))
        if name and name not in seen:
            seen.add(name)
            cities.append((name, sehir_id))
    return cities


def _to_date(date_str):
    return date_str if isinstance(date_str, datetime.date) else datetime.date.fromisoformat(str(date_str))


def day_program_url(date_str):
    """Build TJK daily program main page URL (used to discover SehirId values)."""
    d = _to_date(date_str)
    ds = urllib.parse.quote(d.strftime("%d/%m/%Y"), safe="")
    return f"https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisProgrami?QueryParameter_Tarih={ds}"


def city_program_url(date_str, city, sehir_id):
    """Build TJK AJAX city program URL (requires X-Requested-With: XMLHttpRequest)."""
    d = _to_date(date_str)
    ds = urllib.parse.quote(d.strftime("%d/%m/%Y"), safe="")
    city_enc = urllib.parse.quote(str(city), safe="")
    return (
        "https://www.tjk.org/TR/YarisSever/Info/Sehir/GunlukYarisProgrami"
        f"?SehirId={int(sehir_id)}&QueryParameter_Tarih={ds}&SehirAdi={city_enc}&Era=today"
    )


def minutes_to_post(now_dt, date_str, race_time):
    """Return minutes remaining until post time in Europe/Istanbul (negative if passed)."""
    d = _to_date(date_str)
    hh_s, mm_s = str(race_time).strip().replace(".", ":").split(":", 1)
    post_dt = datetime.datetime(d.year, d.month, d.day, int(hh_s), int(mm_s), tzinfo=IST_TZ)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST_TZ)
    return (post_dt - now_dt).total_seconds() / 60.0


def seconds_to_sleep(known_mtps, interval, fast_interval, window_min):
    """Return (sleep_sec, fetch_next) from known race minutes_to_post values."""
    upcoming = [m for m in known_mtps if m >= -3.0]
    if not upcoming:
        return interval, True
    nearest_mtp = min(upcoming)
    if nearest_mtp > window_min + 2.0:
        sleep_sec = max(interval, min(1800, (nearest_mtp - window_min) * 60.0))
        return sleep_sec, False
    if -3.0 <= nearest_mtp <= 20.0:
        return fast_interval, True
    return interval, True


def should_stop(known_mtps, now_dt, date_str):
    """Return True if all known races passed >10 min ago or Istanbul clock passed next-day 02:00."""
    next_day = _to_date(date_str) + datetime.timedelta(days=1)
    cutoff = datetime.datetime(next_day.year, next_day.month, next_day.day, 2, 0, tzinfo=IST_TZ)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=IST_TZ)
    if now_dt >= cutoff:
        return True
    mtps = list(known_mtps)
    return bool(mtps) and all(m < -10.0 for m in mtps)


def init_live_db(path):
    """Initialize standalone SQLite database for live odds snapshots."""
    p = str(path)
    if p != ":memory:":
        parent = os.path.dirname(p)
        if parent:
            os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(p, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS live_odds (
            captured_at TEXT,
            race_id TEXT,
            prog_no INTEGER,
            ganyan_live REAL,
            agf_pct REAL,
            agf_rank INTEGER,
            race_time TEXT,
            minutes_to_post REAL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_live_odds_race_captured ON live_odds(race_id, captured_at)"
    )
    conn.commit()
    return conn


def insert_snapshots(conn, rows):
    """Insert snapshot rows in a single executemany + commit."""
    params = [
        (
            r["captured_at"],
            r["race_id"],
            r["prog_no"],
            r.get("ganyan_live"),
            r.get("agf_pct"),
            r.get("agf_rank"),
            r.get("race_time"),
            r.get("minutes_to_post"),
        )
        if isinstance(r, dict)
        else tuple(r)
        for r in rows
    ]
    if not params:
        return 0
    conn.executemany(
        """
        INSERT INTO live_odds (
            captured_at, race_id, prog_no, ganyan_live,
            agf_pct, agf_rank, race_time, minutes_to_post
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        params,
    )
    conn.commit()
    return len(params)
