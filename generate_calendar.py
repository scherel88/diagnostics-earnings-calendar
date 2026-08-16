import glob
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EVENTS_FILE = ROOT / "events.json"
ICS_FILE = ROOT / "earnings.ics"
RESULTS_DIR = ROOT / "results"


def load_results():
    out = {}
    for path in sorted(RESULTS_DIR.glob("*.json")):
        for item in json.loads(path.read_text(encoding="utf-8")):
            key = (item["company"], int(item["quarter"]), int(item["fiscal_year"]))
            out[key] = item
    return out


def unfold_ics(text):
    return re.sub(r"\r?\n[ \t]", "", text)


def existing_uids():
    if not ICS_FILE.exists():
        return {}
    text = unfold_ics(ICS_FILE.read_text(encoding="utf-8"))
    out = {}
    for block in re.findall(r"BEGIN:VEVENT\r?\n(.*?)\r?\nEND:VEVENT", text, flags=re.S):
        sm = re.search(r"^SUMMARY:(.+)$", block, flags=re.M)
        um = re.search(r"^UID:(.+)$", block, flags=re.M)
        dm = re.search(r"^DESCRIPTION:(.+)$", block, flags=re.M)
        if not (sm and um and dm):
            continue
        desc = dm.group(1).replace("\\n", "\n")
        ym = re.search(r"Fiscal year:\s*(\d{4})", desc)
        if not ym:
            ym = re.search(r"FINANCIAL SUMMARY[^\d]*(?:Q\d\s+)?(\d{4})", desc)
        if ym:
            out[(sm.group(1).strip(), int(ym.group(1)))] = um.group(1).strip()
    return out


def escape_ics(value):
    return (str(value).replace("\\", "\\\\").replace("\n", "\\n")
            .replace(",", "\\,").replace(";", "\\;"))


def fold_line(line, limit=73):
    raw = line.encode("utf-8")
    parts = []
    while len(raw) > 75:
        cut = min(limit, len(raw))
        while cut > 0 and cut < len(raw) and (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        parts.append(raw[:cut].decode("utf-8"))
        raw = raw[cut:]
    parts.append(raw.decode("utf-8"))
    return "\r\n ".join(parts)


def fallback_uid(company, quarter, fiscal_year):
    key = f"{company}|{quarter}|{fiscal_year}|diagnostics-earnings-calendar"
    return hashlib.sha1(key.encode()).hexdigest()[:20] + "@diagnostics-earnings-calendar"


def description(event, result):
    q = int(event["quarter"])
    fy = int(event["fiscal_year"])
    lines = [f"FINANCIAL SUMMARY - Q{q} {fy}", ""]
    if result and result.get("status", "published") == "published":
        lines.extend(f"- {line}" for line in result.get("lines", []))
        if result.get("results_url"):
            lines.extend(["", f"Official financial results: {result['results_url']}"])
    else:
        lines.extend([
            "Official financial results have not yet been verified on the company's investor-relations site.",
            "This event is monitored daily and will be updated automatically when an official company release is available."
        ])
    lines.extend([
        "",
        f"Earnings call/webcast: {event['webcast']}",
        f"Official earnings-call source: {event['source']}"
    ])
    return "\n".join(lines)


def main():
    events = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    results = load_results()
    old_uids = existing_uids()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    prepared = []
    for event in events:
        key = (event["company"], int(event["quarter"]), int(event["fiscal_year"]))
        result = results.get(key)
        if result and result.get("start_override"):
            event = dict(event)
            event["start"] = result["start_override"]
        prepared.append((event, result))

    prepared.sort(key=lambda pair: pair[0]["start"])
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//scherel88//Diagnostics Earnings Calendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Diagnostics Earnings Calls",
        "X-WR-CALDESC:Earnings conference calls for selected diagnostics and precision oncology companies.",
        "X-WR-TIMEZONE:America/New_York",
        "REFRESH-INTERVAL;VALUE=DURATION:P1D",
        "X-PUBLISHED-TTL:P1D",
    ]

    for event, result in prepared:
        q = int(event["quarter"])
        fy = int(event["fiscal_year"])
        title = f"Q{q} {event['company']} Earnings Conference Call"
        start = datetime.fromisoformat(event["start"])
        end = start + timedelta(hours=1)
        uid = old_uids.get((title, fy), fallback_uid(event["company"], q, fy))
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp}",
            f"LAST-MODIFIED:{stamp}",
            f"DTSTART:{start.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
            f"SUMMARY:{escape_ics(title)}",
            f"LOCATION:{escape_ics(event['webcast'])}",
            f"URL:{event['webcast']}",
            f"DESCRIPTION:{escape_ics(description(event, result))}",
            "STATUS:CONFIRMED",
            "TRANSP:OPAQUE",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    output = "\r\n".join(fold_line(line) for line in lines) + "\r\n"
    ICS_FILE.write_text(output, encoding="utf-8", newline="")


if __name__ == "__main__":
    main()
