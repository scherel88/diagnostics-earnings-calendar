import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ics", action="store_true")
    args = parser.parse_args()
    events = {}
    for path in sorted(ROOT.glob("events*.json")):
        for event in json.loads(path.read_text(encoding="utf-8")):
            for field in ("company", "fiscal_year", "start", "webcast", "source"):
                if not event.get(field):
                    raise ValueError(f"{path}: missing {field}")
            start = datetime.fromisoformat(event["start"])
            if start.utcoffset() is None:
                raise ValueError(f"Missing UTC offset: {event}")
            if not event["webcast"].startswith("https://") or not event["source"].startswith("https://"):
                raise ValueError(f"Non-HTTPS source or webcast: {event}")
            key = ("investor", event["event_id"]) if event.get("event_id") else (event["company"], event.get("quarter", event.get("period")), event["fiscal_year"])
            if key in events and events[key] != event:
                raise ValueError(f"Conflicting duplicate event: {key}")
            events[key] = event
    if args.ics:
        results = {}
        for path in sorted((ROOT / "results").glob("*.json")):
            for item in json.loads(path.read_text(encoding="utf-8")):
                key = ("investor", item["event_id"]) if item.get("event_id") else (item["company"], item.get("quarter", item.get("period")), item["fiscal_year"])
                results[key] = item
        content = (ROOT / "earnings.ics").read_text(encoding="utf-8")
        unfolded = re.sub(r"\n[ \t]", "", content)
        blocks = re.findall(r"BEGIN:VEVENT\n(.*?)\nEND:VEVENT", unfolded, flags=re.S)
        uids = set()
        for block in blocks:
            uid = re.search(r"^UID:(.+)$", block, flags=re.M)
            if not uid or uid.group(1) in uids:
                raise ValueError("Missing or duplicate calendar UID")
            uids.add(uid.group(1))
        for event in events.values():
            key = ("investor", event["event_id"]) if event.get("event_id") else (event["company"], event.get("quarter", event.get("period")), event["fiscal_year"])
            actual_start = results.get(key, {}).get("start_override", event["start"])
            start = datetime.fromisoformat(actual_start).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            label = event.get("title") if event.get("event_id") else (f"Q{event['quarter']} {event['company']} Earnings Conference Call" if event.get("quarter") is not None else f"{event['period']} {event['company']} {event.get('event_type', 'Financial Results Presentation')}")
            if not any(f"DTSTART:{start}" in b and f"SUMMARY:{label}" in b for b in blocks):
                raise ValueError(f"Event missing from ICS: {event['company']} {event['start']}")
        if len(blocks) < len(events):
            raise ValueError("Calendar has fewer events than source records")
    print(f"Validated {len(events)} unique event records" + (" and calendar" if args.ics else ""))

if __name__ == "__main__":
    main()
