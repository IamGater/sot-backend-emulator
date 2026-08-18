"""
extract_fixtures.py — turns real captured traffic (../flows.jsonl, produced
by the sniffer) into replayable fixtures under fixtures/data/.

For every logged request whose path starts with one of the path prefixes
the game's own discovery service advertises (derived from
../discovery_full.json, so we don't pick up unrelated OS/telemetry traffic
like msftncsi checks) and which got a 2xx response, this keeps the *last*
such response seen — headers minus per-connection/hop-by-hop noise, plus
body — as fixtures/data/<METHOD>_<sanitized-path>.json.

Bodies are stored losslessly (fixture["body_encoding"] = "utf8"/"base64",
matching flow.py's Flow.to_dict()) using flows.jsonl's body_raw field when
it's present. That field only exists in entries captured *after* the
sniffer gained raw-body support — older flows.jsonl entries only have the
lossy, truncated, pretty-printed body_preview, and for those this falls
back to the old text-only heuristic (skipping anything that looks
corrupted). If your capture predates that change, endpoints using a
non-text encoding (seen as response header "X-Encoding: sot") will still
be missing here — re-run the sniffer against the game to recapture them,
then re-run this script.

Re-run any time flows.jsonl has new traffic worth capturing: it fully
clears fixtures/data/ and rebuilds it each time, so stale fixtures never
linger.

Usage:
    python extract_fixtures.py
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

import config

# Response headers that are per-connection/per-request noise and must not be
# replayed verbatim (wrong Content-Length after re-encoding, stale Date,
# a request-tracing id that means nothing coming from us, etc.).
DROP_RESPONSE_HEADERS = {
    "content-length", "content-encoding", "connection", "date",
    "server", "x-servicefabricrequestid", "keep-alive", "transfer-encoding",
}

# flow.py's HttpMessage.text_preview() truncates at 40000 chars and appends
# this marker — such a body can't be replayed byte-for-byte, so skip it.
_TRUNCATION_MARKER = "more chars truncated>"

# Legacy fallback only (see module docstring): some endpoints (seen via
# response header "X-Encoding: sot") send a custom binary encoding, not the
# JSON their Content-Type claims. flows.jsonl entries predating body_raw
# support only have text_preview(), which decodes as UTF-8 with
# errors="replace" — lossy for binary, showing up as U+FFFD. There's no
# recovering those bytes from an old capture; skip rather than replay
# corrupted binary.
_REPLACEMENT_CHAR = "�"


def _known_path_prefixes() -> list[str]:
    with open(config.DISCOVERY_SOURCE, "r", encoding="utf-8") as f:
        source = json.load(f)
    prefixes = set()
    for entry in source.values():
        path = urlsplit(entry["url"]).path
        segs = [s for s in path.split("/") if s][:2]  # first 1-2 segments identify the service
        if segs:
            prefixes.add("/" + "/".join(segs))
    return sorted(prefixes)


def _safe_name(method: str, path: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "root"
    return f"{method.upper()}_{slug}.json"


def extract() -> tuple[int, int]:
    prefixes = _known_path_prefixes()
    config.FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    for old in config.FIXTURES_DIR.glob("*.json"):
        old.unlink()

    kept = 0
    skipped_truncated = 0
    skipped_binary = 0
    with open(config.FLOWS_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                flow = json.loads(line)
            except json.JSONDecodeError:
                continue

            status = flow.get("status")
            resp = flow.get("response")
            req = flow.get("request")
            if not status or not status.startswith("2") or not resp or not req:
                continue

            path = urlsplit(flow["url"]).path
            if not any(path.startswith(p) for p in prefixes):
                continue

            if "body_encoding" in resp:
                # new-format entry: lossless body, byte-exact even for binary
                if resp.get("body_raw_truncated"):
                    skipped_truncated += 1
                    continue
                body_encoding = resp["body_encoding"]
                body = "" if body_encoding == "empty" else resp.get("body_raw", "")
            else:
                # legacy entry (captured before raw-body support) — best effort only
                body = resp.get("body_preview", "")
                if _TRUNCATION_MARKER in body:
                    skipped_truncated += 1
                    continue
                if _REPLACEMENT_CHAR in body:
                    skipped_binary += 1
                    continue
                body_encoding = "utf8"

            headers = [[k, v] for k, v in resp["headers"] if k.lower() not in DROP_RESPONSE_HEADERS]

            fixture = {
                "method": flow["method"],
                "path": path,
                "status": int(status),
                "headers": headers,
                "body_encoding": body_encoding,
                "body": body,
                "source_url": flow["url"],  # traceability only, unused at replay time
            }
            out_path = config.FIXTURES_DIR / _safe_name(flow["method"], path)
            out_path.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
            kept += 1

    return kept, skipped_truncated, skipped_binary


if __name__ == "__main__":
    kept, skipped_truncated, skipped_binary = extract()
    print(f"wrote {kept} fixture(s) to {config.FIXTURES_DIR}")
    if skipped_truncated:
        print(f"skipped {skipped_truncated} response(s): body was truncated in flows.jsonl (>40000-char preview)")
    if skipped_binary:
        print(
            f"skipped {skipped_binary} response(s): custom binary encoding (X-Encoding: sot), "
            "already corrupted by lossy UTF-8 capture in flows.jsonl - see this script's docstring"
        )
