"""Rejection log: killed candidates recorded with stage, score, and reason —
then marked with forward outcomes, so the swarm's skips can be judged.

Mentor feedback: "log the rejected ideas and track them the same way;
otherwise we can't say the skips were right."

Records are parsed from the mandated DOSSIER/SKEPTIC output blocks that
stage B already produces per candidate, so the log costs no extra LLM or
UW calls. Import-light like `specstore` (no crew imports at module level):
importing `swarm.crew` spawns the UW MCP server process.

Outcomes are point-in-time by construction: the forward 7-trading-day
return is read from the same historical close series the gate uses, so a
rejection recorded on any past date can be judged on real closes.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

DOSSIER_FLOOR = 6.0
FWD_BARS = 7  # trading days of forward outcome, matching the executor's default DTE

REJECTIONS_FILE = Path(__file__).resolve().parent.parent / "data" / "rejections" / "rejections.json"
RAW_DIR = Path(__file__).resolve().parent.parent / "reports" / "raw"

_DOSIER_RE = re.compile(r"VERDICT:\s*(BULLISH|BEARISH|NO-TRADE)", re.I)
_SCORE_RE = re.compile(r"SCORE:\s*([0-9](?:\.\d+)?)\s*/?\s*(?:10)?", re.I)
_SKEPTIC_RE = re.compile(r"OVERRIDES:\s*(keep|downgrade|kill)", re.I)
_REASON_RE = re.compile(r"REASONING:\s*(.+)", re.I | re.S)


def _reason(text: str, cap: int = 220) -> str:
    m = _REASON_RE.search(text)
    if not m:
        return ""
    return re.sub(r"\s+", " ", m.group(1)).strip()[:cap]


def parse_dossier(text: str) -> tuple[float | None, str | None, str]:
    """(score, verdict, reasoning) from a mandated DOSSIER block."""
    v = _DOSIER_RE.search(text)
    s = _SCORE_RE.search(text)
    return (
        float(s.group(1)) if s else None,
        v.group(1).upper() if v else None,
        _reason(text),
    )


def parse_skeptic(text: str) -> tuple[str | None, str]:
    """(overrides action, reasoning) from a mandated SKEPTIC block."""
    m = _SKEPTIC_RE.search(text)
    return (m.group(1).lower() if m else None), _reason(text)


def _killed_by(score: float | None, verdict: str | None, action: str | None) -> str:
    """First fatal stage in pipeline order: dossier floor, then skeptic, then chair."""
    if verdict == "NO-TRADE" or (score is not None and score < DOSSIER_FLOOR):
        return "dossier_floor"
    if action == "kill":
        return "skeptic_kill"
    return "chair"


def build_rejection(day: date, rank: int, ticker: str,
                    dossier_text: str, skeptic_text: str) -> dict:
    score, verdict, d_reason = parse_dossier(dossier_text)
    action, s_reason = parse_skeptic(skeptic_text)
    killer = _killed_by(score, verdict, action)
    reason = {"dossier_floor": d_reason, "skeptic_kill": s_reason, "chair": s_reason or d_reason}[killer]
    return {
        "rejection_id": f"{day.isoformat()}_{ticker}",
        "date": day.isoformat(),
        "ticker": ticker,
        "rank": rank,
        "dossier_verdict": verdict,
        "dossier_score": score,
        "skeptic_action": action,
        "killed_by": killer,
        "reason": reason,
        "outcome": None,
    }


def load_rejections(path: Path | None = None) -> list[dict]:
    path = Path(path) if path is not None else REJECTIONS_FILE
    try:
        recs = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(recs, list):
        return []
    return [r for r in recs if isinstance(r, dict) and "rejection_id" in r]


def save_merged(new: list[dict], path: Path | None = None) -> list[dict]:
    """Upsert by rejection_id: new records replace same-id older ones,
    everything else is preserved (same accumulate semantics as the spec store)."""
    path = Path(path) if path is not None else REJECTIONS_FILE
    existing = load_rejections(path)
    new_ids = {r["rejection_id"] for r in new}
    merged = [r for r in existing if r["rejection_id"] not in new_ids] + new
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(merged, indent=2))
    return merged


def record_rejections(day: date, packages: list[tuple[str, str, str]],
                      survivor_tickers: set[str],
                      path: Path | None = None) -> list[dict]:
    """Record every scanned candidate that did NOT become a spec.

    packages: (ticker, dossier_text, skeptic_text) per candidate, in rank
    order. survivor_tickers: underlyings the chair emitted as specs.
    """
    records = []
    for rank, (ticker, d_text, s_text) in enumerate(packages, 1):
        if ticker in survivor_tickers:
            continue
        records.append(build_rejection(day, rank, ticker, d_text, s_text))
    if records:
        save_merged(records, path)
    return records


def has_pending_outcomes(path: Path | None = None) -> bool:
    return any(r.get("outcome") is None for r in load_rejections(path))


def update_outcomes(uw, path: Path | None = None) -> int:
    """Fill in the forward 7-trading-day return for every rejection that
    still lacks one and has enough history. Returns the count updated."""
    from swarm.backtest.gate import CloseSeries  # lazy: keeps module import-light

    recs = load_rejections(path)
    target = Path(path) if path is not None else REJECTIONS_FILE
    updated = 0
    for rec in recs:
        if rec.get("outcome") is not None:
            continue
        try:
            series = CloseSeries.from_uw(uw, rec["ticker"])
        except Exception:
            continue  # no usable close series for this ticker (unknown symbol etc.)
        iso = [d.isoformat() for d in series.dates]
        if rec["date"] not in iso:
            continue  # date not in the series (holiday label or unknown ticker)
        i = iso.index(rec["date"])
        if i + FWD_BARS >= len(series.dates):
            continue  # not enough forward bars yet — retry on a later mark
        spot0, spot1 = series.closes[i], series.closes[i + FWD_BARS]
        rec["outcome"] = {
            "spot_at_rejection": round(spot0, 2),
            "spot_7_trading_days_later": round(spot1, 2),
            "fwd_return_7d": round(spot1 / spot0 - 1.0, 4),
        }
        updated += 1
    if updated:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(recs, indent=2))
    return updated


def backfill_from_transcripts(raw_dir: Path | None = None,
                              spec_file: Path | None = None) -> int:
    """Rebuild rejection records from existing reports/raw transcripts.

    Uses the latest transcript per date (re-runs overwrite) and the spec
    store to determine which candidates survived as specs. Returns the
    number of rejection dates processed.
    """
    from swarm.specstore import load_existing as load_specs

    raw = Path(raw_dir) if raw_dir is not None else RAW_DIR
    survivors: dict[str, set[str]] = {}
    for sp in load_specs(spec_file):
        tid = sp.get("trade_id", "")
        if "_" in tid:
            d, t = tid.split("_", 1)
            survivors.setdefault(d, set()).add(t)

    pattern = re.compile(r"^(\d{4}-\d{2}-\d{2})_dossier_(\d+)_([A-Z]+)\.txt$")
    by_day: dict[str, list[tuple[int, str, str, str]]] = {}
    for path in sorted(raw.glob("*_dossier_*.txt")):
        m = pattern.match(path.name)
        if not m:
            continue
        day, rank, ticker = m.group(1), int(m.group(2)), m.group(3)
        skeptic = raw / f"{day}_skeptic_{rank}_{ticker}.txt"
        s_text = skeptic.read_text() if skeptic.exists() else ""
        by_day.setdefault(day, []).append((rank, ticker, path.read_text(), s_text))

    for day, entries in by_day.items():
        packages = [(ticker, d_text, s_text) for _, ticker, d_text, s_text
                    in sorted(entries)]
        record_rejections(date.fromisoformat(day), packages,
                          survivors.get(day, set()))
    return len(by_day)


def main(argv: list[str]) -> int:
    """CLI:
      python -m swarm.rejections list        # print the log
      python -m swarm.rejections mark        # fill forward outcomes (UW closes)
      python -m swarm.rejections backfill    # rebuild from reports/raw transcripts
    """
    if not argv:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "list":
        for r in load_rejections():
            out = r.get("outcome")
            fwd = "n/a" if not out else f"{out['fwd_return_7d']:+.2%}"
            print(f"{r['rejection_id']:22s} killed_by={r['killed_by']:13s} "
                  f"score={r['dossier_score']} fwd7d={fwd}")
        return 0
    if cmd == "mark":
        from swarm.tools.uw import UWMCPClient
        uw = UWMCPClient()
        uw.initialize()
        n = update_outcomes(uw)
        recs = load_rejections()
        print(f"=== REJECTIONS: {n} outcomes updated; "
              f"{len(recs)} records, "
              f"{sum(1 for r in recs if r.get('outcome'))} with outcomes ===")
        return 0
    if cmd == "backfill":
        n = backfill_from_transcripts()
        print(f"=== REJECTIONS: backfilled from transcripts for {n} scan dates ===")
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
