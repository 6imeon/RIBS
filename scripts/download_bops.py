"""
Pull public planning applications from council BOPS APIs.

Islington is not on BOPS yet (404). Live London hosts as of 2026-08:
  camden, barnet, lambeth, southwark

Usage:
  python scripts/download_bops.py camden
  python scripts/download_bops.py camden --force
  python scripts/download_bops.py camden --no-documents

Outputs
-------
data/raw/bops/{council}/
  search/page_NNN.json
  applications/{ref}.json
  documents/{ref}.json
  _manifest.json

data/processed/bops/
  applications.csv
  timeline_events.csv
  documents.csv
  comments.csv
  column_dictionary.csv
  applications_{council}.csv (per-council snapshot)
  ...
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
RAW_ROOT = ROOT / "data" / "raw" / "bops"
PROCESSED = ROOT / "data" / "processed" / "bops"

KNOWN_COUNCILS = (
    "camden",
    "barnet",
    "lambeth",
    "southwark",
    "buckinghamshire",
    "gateshead",
    "medway",
    "newcastle",
    "south-gloucestershire",
)

PAGE_SIZE = 10
USER_AGENT = "RIBS-bops-pull/0.1 (local research; Open Government Licence)"
REQUEST_GAP_S = 0.15


def council_host(council: str) -> str:
    return f"https://{council}.bops.services"


def api_url(council: str, path: str) -> str:
    return f"{council_host(council)}{path}"


def safe_ref(reference: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", reference)


def get_json(url: str, *, timeout: int = 60) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.rename(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def probe_council(council: str) -> dict[str, Any]:
    url = api_url(council, "/api/v2/public/planning_applications/search?page=1&maxresults=1")
    try:
        return get_json(url)
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"Council '{council}' has no public BOPS API at {council_host(council)} "
            f"(HTTP {e.code}). Known live: {', '.join(KNOWN_COUNCILS[:4])}…"
        ) from e
    except urllib.error.URLError as e:
        raise SystemExit(f"Could not reach {council_host(council)}: {e.reason}") from e


def fetch_search_pages(council: str, dest: Path, *, force: bool) -> list[dict[str, Any]]:
    search_dir = dest / "search"
    search_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict[str, Any]] = []
    page = 1
    while True:
        out = search_dir / f"page_{page:03d}.json"
        if out.exists() and out.stat().st_size > 0 and not force:
            payload = load_json(out)
            print(f"CACHED  search page {page}")
        else:
            url = api_url(
                council,
                f"/api/v2/public/planning_applications/search?page={page}&maxresults={PAGE_SIZE}",
            )
            print(f"FETCH   {url}")
            payload = get_json(url)
            write_json(out, payload)
            time.sleep(REQUEST_GAP_S)
        pages.append(payload)
        pag = payload.get("pagination") or {}
        total_pages = int(pag.get("totalPages") or 1)
        n_rows = len(payload.get("data") or [])
        print(f"        page {page}/{total_pages}  rows={n_rows}  total={pag.get('totalResults')}")
        if page >= total_pages or n_rows == 0:
            break
        page += 1
    return pages


def refs_from_search(pages: list[dict[str, Any]]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for payload in pages:
        for row in payload.get("data") or []:
            ref = (row.get("application") or {}).get("reference")
            if ref and ref not in seen:
                seen.add(ref)
                refs.append(ref)
    return refs


def fetch_application(council: str, ref: str, dest: Path, *, force: bool) -> dict[str, Any]:
    out = dest / "applications" / f"{safe_ref(ref)}.json"
    if out.exists() and out.stat().st_size > 0 and not force:
        print(f"CACHED  application {ref}")
        return load_json(out)
    url = api_url(council, f"/api/v2/public/planning_applications/{urllib.parse.quote(ref)}")
    print(f"FETCH   {ref}")
    payload = get_json(url)
    write_json(out, payload)
    time.sleep(REQUEST_GAP_S)
    return payload


def fetch_documents(council: str, ref: str, dest: Path, *, force: bool) -> dict[str, Any] | None:
    out = dest / "documents" / f"{safe_ref(ref)}.json"
    if out.exists() and out.stat().st_size > 0 and not force:
        print(f"CACHED  documents {ref}")
        return load_json(out)
    url = api_url(
        council,
        f"/api/v2/public/planning_applications/{urllib.parse.quote(ref)}/documents",
    )
    print(f"FETCH   documents {ref}")
    try:
        payload = get_json(url)
    except urllib.error.HTTPError as e:
        print(f"WARN    documents {ref}: HTTP {e.code}")
        return None
    write_json(out, payload)
    time.sleep(REQUEST_GAP_S)
    return payload


def dig(obj: Any, *keys: str, default: Any = None) -> Any:
    cur = obj
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def flatten_application(council: str, detail: dict[str, Any]) -> dict[str, Any]:
    app = detail.get("application") or {}
    prop = detail.get("property") or {}
    addr = prop.get("address") or {}
    proposal = detail.get("proposal") or {}
    applicant = detail.get("applicant") or {}
    officer = detail.get("officer") or {}
    consultation = app.get("consultation") or {}
    press = app.get("pressNotice") or {}
    app_type = app.get("type") or {}
    reporting = proposal.get("reportingType") or {}
    boundary = dig(prop, "boundary", "site") or {}
    boundary_props = boundary.get("properties") if isinstance(boundary, dict) else {}
    public_comments = consultation.get("publishedComments") or []
    consultee_comments = consultation.get("consulteeComments") or []
    return {
        "council": council,
        "reference": app.get("reference"),
        "full_reference": app.get("fullReference"),
        "alternative_reference": app.get("alternativeReference"),
        "application_type": app_type.get("value"),
        "application_type_description": app_type.get("description"),
        "status": app.get("status"),
        "decision": app.get("decision"),
        "received_at": app.get("receivedAt"),
        "valid_at": app.get("validAt"),
        "published_at": app.get("publishedAt"),
        "determined_at": app.get("determinedAt"),
        "target_date": app.get("targetDate"),
        "expiry_date": app.get("expiryDate"),
        "consultation_start": consultation.get("startDate"),
        "consultation_end": consultation.get("endDate"),
        "consultation_public_url": consultation.get("publicUrl"),
        "press_notice_required": press.get("required"),
        "press_notice_reason": press.get("reason"),
        "press_notice_published_at": press.get("publishedAt"),
        "public_comment_count": len(public_comments),
        "consultee_comment_count": len(consultee_comments),
        "proposal_description": proposal.get("description"),
        "reporting_type_code": reporting.get("code"),
        "reporting_type_description": reporting.get("description"),
        "address_single_line": addr.get("singleLine"),
        "address_title": addr.get("title"),
        "address_town": addr.get("town"),
        "postcode": addr.get("postcode"),
        "uprn": addr.get("uprn"),
        "latitude": addr.get("latitude"),
        "longitude": addr.get("longitude"),
        "boundary_entity": (boundary_props or {}).get("entity") if isinstance(boundary_props, dict) else None,
        "boundary_reference": (boundary_props or {}).get("reference") if isinstance(boundary_props, dict) else None,
        "applicant_type": applicant.get("type"),
        "ownership_interest": dig(applicant, "ownership", "interest"),
        "officer_name": officer.get("name"),
        "session_id": app.get("sessionId"),
        "source_url": api_url(
            council,
            f"/api/v2/public/planning_applications/{urllib.parse.quote(str(app.get('reference') or ''))}",
        ),
        "register_url": f"https://planningregister.org/{council}/{urllib.parse.quote(str(app.get('reference') or ''))}",
    }


APPLICATION_COLUMNS: list[tuple[str, str, str]] = [
    ("council", "yes", "BOPS council slug (e.g. camden)."),
    ("reference", "yes", "Council application reference (primary key within a council)."),
    ("full_reference", "yes", "Prefixed reference (e.g. CMD-26-00275-HAPP)."),
    ("alternative_reference", "maybe", "Legacy / alternate portal reference if present."),
    ("application_type", "yes", "ODP type code: pp.full.householder, ldc.proposed, etc."),
    ("application_type_description", "yes", "Human-readable application type."),
    ("status", "yes", "Lifecycle status from BOPS (in_assessment, determined, withdrawn, …)."),
    ("decision", "yes", "Outcome when determined: granted / refused / null if open."),
    ("received_at", "yes", "When the LPA received the application (timeline)."),
    ("valid_at", "yes", "When validated (timeline)."),
    ("published_at", "yes", "When published on the public register (timeline)."),
    ("determined_at", "yes", "Decision datetime (timeline); null if not yet decided."),
    ("target_date", "yes", "Statutory target decision date."),
    ("expiry_date", "yes", "Application expiry date."),
    ("consultation_start", "yes", "Public consultation start date (timeline)."),
    ("consultation_end", "yes", "Public consultation end date (timeline)."),
    ("consultation_public_url", "maybe", "Council URL for commenting / viewing consultation."),
    ("press_notice_required", "maybe", "Whether a press notice was required."),
    ("press_notice_reason", "maybe", "Why (e.g. Conservation area)."),
    ("press_notice_published_at", "yes", "Press notice publish date (timeline)."),
    ("public_comment_count", "yes", "Count of published public comments on the detail payload."),
    ("consultee_comment_count", "yes", "Count of specialist consultee comments."),
    ("proposal_description", "yes", "Free-text proposal description."),
    ("reporting_type_code", "maybe", "GLA / reporting classification code if present."),
    ("reporting_type_description", "maybe", "GLA / reporting classification label."),
    ("address_single_line", "yes", "Site address as a single line."),
    ("address_title", "maybe", "Short address title."),
    ("address_town", "maybe", "Town / city."),
    ("postcode", "yes", "Site postcode."),
    ("uprn", "yes", "Unique Property Reference Number — best join key to other datasets."),
    ("latitude", "yes", "Site latitude."),
    ("longitude", "yes", "Site longitude."),
    ("boundary_entity", "maybe", "planning.data.gov.uk title-boundary entity id."),
    ("boundary_reference", "maybe", "Title boundary reference."),
    ("applicant_type", "maybe", "individual / organisation / etc."),
    ("ownership_interest", "maybe", "Applicant ownership interest (e.g. owner)."),
    ("officer_name", "maybe", "Case officer display name."),
    ("session_id", "no", "Internal PlanX/BOPS session id — rarely useful for analysis."),
    ("source_url", "yes", "BOPS JSON detail URL used for this row."),
    ("register_url", "yes", "Human-facing Digital Planning Register page."),
]


def build_timeline(council: str, detail: dict[str, Any]) -> list[dict[str, Any]]:
    app = detail.get("application") or {}
    consultation = app.get("consultation") or {}
    press = app.get("pressNotice") or {}
    ref = app.get("reference")
    candidates = [
        ("received", app.get("receivedAt"), "Application received by LPA"),
        ("validated", app.get("validAt"), "Application validated"),
        ("published", app.get("publishedAt"), "Published on public register"),
        ("consultation_start", consultation.get("startDate"), "Public consultation started"),
        ("consultation_end", consultation.get("endDate"), "Public consultation ended"),
        ("press_notice", press.get("publishedAt"), "Press notice published"),
        (
            "determined",
            app.get("determinedAt"),
            f"Decision: {app.get('decision')}" if app.get("decision") else "Decision issued",
        ),
    ]
    events: list[dict[str, Any]] = []
    for event_type, when, label in candidates:
        if not when:
            continue
        events.append(
            {
                "council": council,
                "reference": ref,
                "event_type": event_type,
                "event_at": when,
                "label": label,
                "status_at_pull": app.get("status"),
                "decision": app.get("decision"),
            }
        )
    for c in consultation.get("publishedComments") or []:
        if c.get("receivedAt"):
            events.append(
                {
                    "council": council,
                    "reference": ref,
                    "event_type": "public_comment",
                    "event_at": c.get("receivedAt"),
                    "label": f"Public comment ({c.get('summaryTag') or 'unspecified'})",
                    "status_at_pull": app.get("status"),
                    "decision": app.get("decision"),
                }
            )
    for c in consultation.get("consulteeComments") or []:
        if c.get("receivedAt"):
            events.append(
                {
                    "council": council,
                    "reference": ref,
                    "event_type": "consultee_comment",
                    "event_at": c.get("receivedAt"),
                    "label": "Specialist consultee comment",
                    "status_at_pull": app.get("status"),
                    "decision": app.get("decision"),
                }
            )
    events.sort(key=lambda e: (e["event_at"] or "", e["event_type"]))
    return events


def flatten_documents(council: str, ref: str, docs_payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not docs_payload:
        return []
    rows: list[dict[str, Any]] = []
    for f in docs_payload.get("files") or []:
        types = f.get("type") or []
        type_values = ";".join(t.get("value") or "" for t in types if isinstance(t, dict))
        type_descs = ";".join(t.get("description") or "" for t in types if isinstance(t, dict))
        meta = f.get("metadata") or {}
        rows.append(
            {
                "council": council,
                "reference": ref,
                "file_name": f.get("name"),
                "file_url": f.get("url"),
                "created_at": f.get("createdAt"),
                "type_values": type_values,
                "type_descriptions": type_descs,
                "byte_size": meta.get("byteSize"),
                "content_type": meta.get("contentType"),
                "applicant_description": f.get("applicantDescription"),
                "is_decision_notice": False,
            }
        )
    notice = docs_payload.get("decisionNotice") or {}
    if notice.get("url") or notice.get("name"):
        rows.append(
            {
                "council": council,
                "reference": ref,
                "file_name": notice.get("name"),
                "file_url": notice.get("url"),
                "created_at": None,
                "type_values": "decision_notice",
                "type_descriptions": "Decision notice",
                "byte_size": None,
                "content_type": "application/pdf",
                "applicant_description": None,
                "is_decision_notice": True,
            }
        )
    return rows


def flatten_comments(council: str, detail: dict[str, Any]) -> list[dict[str, Any]]:
    app = detail.get("application") or {}
    consultation = app.get("consultation") or {}
    ref = app.get("reference")
    rows: list[dict[str, Any]] = []
    for i, c in enumerate(consultation.get("publishedComments") or []):
        rows.append(
            {
                "council": council,
                "reference": ref,
                "comment_kind": "public",
                "comment_index": i,
                "received_at": c.get("receivedAt"),
                "summary_tag": c.get("summaryTag"),
                "comment_text": c.get("comment"),
            }
        )
    for i, c in enumerate(consultation.get("consulteeComments") or []):
        rows.append(
            {
                "council": council,
                "reference": ref,
                "comment_kind": "consultee",
                "comment_index": i,
                "received_at": c.get("receivedAt"),
                "summary_tag": None,
                "comment_text": c.get("comment"),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def write_column_dictionary(path: Path) -> None:
    rows = [{"column": n, "relevance": r, "description": d} for n, r, d in APPLICATION_COLUMNS]
    write_csv(path, rows, ["column", "relevance", "description"])


def merge_csv_by_keys(
    path: Path,
    new_rows: list[dict[str, Any]],
    fieldnames: list[str],
    key_fields: list[str],
    *,
    replace_council: str | None = None,
) -> list[dict[str, Any]]:
    existing: list[dict[str, Any]] = []
    if path.exists() and path.stat().st_size > 0:
        with path.open(encoding="utf-8", newline="") as fh:
            existing = list(csv.DictReader(fh))
    if replace_council:
        existing = [r for r in existing if r.get("council") != replace_council]
    keyed: dict[tuple, dict[str, Any]] = {}
    for r in existing:
        keyed[tuple(r.get(k) for k in key_fields)] = r
    for r in new_rows:
        keyed[tuple(r.get(k) for k in key_fields)] = r
    merged = list(keyed.values())
    write_csv(path, merged, fieldnames)
    return merged


def _counts(rows: list[dict[str, Any]], field: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        key = r.get(field)
        key_s = "null" if key in (None, "") else str(key)
        out[key_s] = out.get(key_s, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def pull_council(council: str, *, force: bool, fetch_docs: bool) -> dict[str, Any]:
    council = council.strip().lower().replace(" ", "-").replace("_", "-")
    print(f"\n=== BOPS pull: {council} ===")
    print(f"Host: {council_host(council)}")
    probe = probe_council(council)
    print(f"Public applications reported: {dig(probe, 'pagination', 'totalResults', default='?')}")
    dest = RAW_ROOT / council
    dest.mkdir(parents=True, exist_ok=True)
    pages = fetch_search_pages(council, dest, force=force)
    refs = refs_from_search(pages)
    print(f"Unique references from search: {len(refs)}")

    applications: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []

    for i, ref in enumerate(refs, 1):
        print(f"[{i}/{len(refs)}] {ref}")
        detail = fetch_application(council, ref, dest, force=force)
        applications.append(flatten_application(council, detail))
        timeline.extend(build_timeline(council, detail))
        comments.extend(flatten_comments(council, detail))
        if fetch_docs:
            docs = fetch_documents(council, ref, dest, force=force)
            documents.extend(flatten_documents(council, ref, docs))

    PROCESSED.mkdir(parents=True, exist_ok=True)
    app_fields = [c[0] for c in APPLICATION_COLUMNS]
    timeline_fields = ["council", "reference", "event_type", "event_at", "label", "status_at_pull", "decision"]
    doc_fields = [
        "council", "reference", "file_name", "file_url", "created_at", "type_values",
        "type_descriptions", "byte_size", "content_type", "applicant_description", "is_decision_notice",
    ]
    comment_fields = ["council", "reference", "comment_kind", "comment_index", "received_at", "summary_tag", "comment_text"]

    write_csv(PROCESSED / f"applications_{council}.csv", applications, app_fields)
    write_csv(PROCESSED / f"timeline_events_{council}.csv", timeline, timeline_fields)
    write_csv(PROCESSED / f"documents_{council}.csv", documents, doc_fields)
    write_csv(PROCESSED / f"comments_{council}.csv", comments, comment_fields)
    write_column_dictionary(PROCESSED / "column_dictionary.csv")

    merge_csv_by_keys(PROCESSED / "applications.csv", applications, app_fields, ["council", "reference"], replace_council=council)
    merge_csv_by_keys(
        PROCESSED / "timeline_events.csv", timeline, timeline_fields,
        ["council", "reference", "event_type", "event_at", "label"], replace_council=council,
    )
    merge_csv_by_keys(
        PROCESSED / "documents.csv", documents, doc_fields,
        ["council", "reference", "file_url", "file_name"], replace_council=council,
    )
    merge_csv_by_keys(
        PROCESSED / "comments.csv", comments, comment_fields,
        ["council", "reference", "comment_kind", "comment_index"], replace_council=council,
    )

    manifest = {
        "council": council,
        "host": council_host(council),
        "pulled_at": datetime.now(timezone.utc).isoformat(),
        "force": force,
        "fetch_documents": fetch_docs,
        "search_total_results": dig(pages[-1] if pages else {}, "pagination", "totalResults"),
        "references_count": len(refs),
        "applications_count": len(applications),
        "timeline_events_count": len(timeline),
        "documents_count": len(documents),
        "comments_count": len(comments),
        "status_counts": _counts(applications, "status"),
        "decision_counts": _counts(applications, "decision"),
        "application_type_counts": _counts(applications, "application_type"),
    }
    write_json(dest / "_manifest.json", manifest)
    write_json(PROCESSED / f"manifest_{council}.json", manifest)
    print("\n=== Done ===")
    print(json.dumps({k: manifest[k] for k in (
        "council", "references_count", "timeline_events_count", "documents_count", "comments_count",
        "status_counts", "decision_counts",
    )}, indent=2))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("council", help="Council slug, e.g. camden. Islington is not on BOPS yet.")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if cached files exist.")
    parser.add_argument("--no-documents", action="store_true", help="Skip /documents endpoints.")
    args = parser.parse_args(argv)
    if args.council.lower() in {"islington", "isl"}:
        print(
            "NOTE: Islington has no public BOPS host "
            "(https://islington.bops.services → 404).\n"
            "Pilot London boroughs with live data: camden, barnet, lambeth, southwark.\n"
            "Re-run with: python scripts/download_bops.py camden\n",
            file=sys.stderr,
        )
        return 2
    pull_council(args.council, force=args.force, fetch_docs=not args.no_documents)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
