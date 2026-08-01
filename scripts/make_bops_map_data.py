"""Export BOPS applications + timelines for the map UI.

Reads data/processed/bops/{applications,timeline_events}.csv and writes
app/data/bops_apps.json — compact, only apps with coordinates.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed" / "bops"
OUT = ROOT / "app" / "data" / "bops_apps.json"

TYPE_LABEL = {
    "pp.full.householder": "Householder",
    "pp.full.householder.retro": "Householder (retrospective)",
    "ldc.proposed": "Lawful development (proposed)",
    "ldc.existing": "Lawful development (existing)",
    "ldc.listedBuildingWorks": "Lawful development (listed building)",
    "approval.conditions": "Discharge of conditions",
}

# Milestone events shown on the timeline (comments are aggregated).
MILESTONE = {
    "received": "Received",
    "validated": "Validated",
    "published": "Published",
    "consultation_start": "Consultation opened",
    "consultation_end": "Consultation closed",
    "press_notice": "Press notice",
    "determined": "Decision",
}

COUNCIL_LABEL = {
    "camden": "Camden",
    "barnet": "Barnet",
    "lambeth": "Lambeth",
    "southwark": "Southwark",
}


def short_date(s: str | None) -> str | None:
    if not s:
        return None
    return s[:10]


def outcome_bucket(status: str | None, decision: str | None) -> str:
    """Standardised outcome for colouring / filters."""
    d = (decision or "").lower()
    st = (status or "").lower()
    if d == "granted":
        return "granted"
    if d == "refused":
        return "refused"
    if "withdraw" in st:
        return "withdrawn"
    if st in {"closed", "appeal dismissed"}:
        return "closed"
    if st in {"determined"} and not d:
        return "closed"
    return "in_progress"


def build_events(rows: list[dict]) -> list[dict]:
    """Collapse comment spam; keep ordered milestones with standardised labels."""
    milestones: list[dict] = []
    comments = 0
    consultee = 0
    for r in rows:
        k = r.get("event_type") or ""
        at = short_date(r.get("event_at"))
        if k == "public_comment":
            comments += 1
            continue
        if k == "consultee_comment":
            consultee += 1
            continue
        if k not in MILESTONE or not at:
            continue
        label = MILESTONE[k]
        if k == "determined" and r.get("decision"):
            label = f"Decision · {r['decision'].capitalize()}"
        milestones.append({"k": k, "at": at, "l": label})

    # Stable chronological order; keep first occurrence of each milestone key
    # except determined (always keep).
    seen: set[str] = set()
    out: list[dict] = []
    for e in sorted(milestones, key=lambda e: (e["at"], e["k"])):
        if e["k"] in seen and e["k"] != "determined":
            continue
        seen.add(e["k"])
        out.append(e)

    # Insert aggregated comment markers at the earliest comment date if we have one
    comment_dates = [
        short_date(r.get("event_at"))
        for r in rows
        if r.get("event_type") in {"public_comment", "consultee_comment"} and r.get("event_at")
    ]
    if comments or consultee:
        at = min(comment_dates) if comment_dates else out[0]["at"] if out else None
        parts = []
        if comments:
            parts.append(f"{comments} public comment{'s' if comments != 1 else ''}")
        if consultee:
            parts.append(f"{consultee} consultee")
        if at:
            out.append({"k": "comments", "at": at, "l": " · ".join(parts)})
            out.sort(key=lambda e: (e["at"], 0 if e["k"] != "comments" else 1, e["k"]))

    return out


def main() -> int:
    apps_path = PROC / "applications.csv"
    ev_path = PROC / "timeline_events.csv"
    if not apps_path.exists() or not ev_path.exists():
        raise SystemExit(
            f"Missing BOPS processed CSVs. Run: python scripts/download_bops.py camden"
        )

    apps = list(csv.DictReader(apps_path.open(encoding="utf-8")))
    events_by: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in csv.DictReader(ev_path.open(encoding="utf-8")):
        events_by[(e["council"], e["reference"])].append(e)

    out_apps: list[dict] = []
    skipped_no_xy = 0
    for a in apps:
        try:
            lat = float(a["latitude"]) if a.get("latitude") else None
            lon = float(a["longitude"]) if a.get("longitude") else None
        except ValueError:
            lat = lon = None
        if lat is None or lon is None:
            skipped_no_xy += 1
            continue

        key = (a["council"], a["reference"])
        ev = build_events(events_by.get(key, []))
        atype = a.get("application_type") or ""
        out_apps.append(
            {
                "c": a["council"],
                "cl": COUNCIL_LABEL.get(a["council"], a["council"].title()),
                "r": a["reference"],
                "fr": a.get("full_reference") or a["reference"],
                "t": atype,
                "tl": TYPE_LABEL.get(atype, a.get("application_type_description") or atype),
                "st": a.get("status") or "",
                "d": a.get("decision") or "",
                "o": outcome_bucket(a.get("status"), a.get("decision")),
                "y": round(lat, 6),
                "x": round(lon, 6),
                "ad": a.get("address_single_line") or "",
                "pc": a.get("postcode") or "",
                "desc": (a.get("proposal_description") or "").strip(),
                "url": a.get("register_url") or "",
                "ev": ev,
            }
        )

    # Camden first (richest), then by reference
    out_apps.sort(key=lambda a: (0 if a["c"] == "camden" else 1, a["c"], a["r"]))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "BOPS public API (Open Digital Planning pilot)",
        "note": "Pilot applications only — not the full planning register.",
        "count": len(out_apps),
        "skipped_no_coordinates": skipped_no_xy,
        "apps": out_apps,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}  ({len(out_apps)} apps, skipped {skipped_no_xy} without coords)")
    by_o: dict[str, int] = defaultdict(int)
    for a in out_apps:
        by_o[a["o"]] += 1
    print("outcomes:", dict(by_o))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
