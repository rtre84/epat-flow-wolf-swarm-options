"""flowwolf scan orchestration. "Swarm proposes, code disposes."

Pipeline (Phase 2):
  1. crew stage A: regime analyst -> flow scout            (one Crew, sequential)
  2. for each candidate (capped MAX_CANDIDATES): dossier -> skeptic crew
  3. crew stage C: chair rewrites surviving ideas into TradeSpec JSONs

Every stage's raw output is persisted to reports/raw/<date>_<stage>.txt for
post-mortems. The chair's JSON blocks are the ONLY thing downstream trusts.
"""
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Callable

from crewai import Agent, Crew, Process, Task

from swarm.llm import LLMConfig
from swarm import prompts, specstore
from swarm.learn import chair_calibration
from swarm.tools.uw_tools import UW_TOOLS

RAW_DIR = Path(__file__).resolve().parent.parent / "reports" / "raw"
SPEC_FILE = specstore.SPEC_FILE  # re-export: daily.py reads crew.SPEC_FILE
MAX_CANDIDATES = 8

TOOL_HINT = "\n\nUnusual Whales tools available: " + ", ".join(
    t.name for t in UW_TOOLS)


def _agent(role: str) -> Agent:
    cfg = LLMConfig()
    return Agent(
        role=role,
        goal=f"You are the {role} of the flowwolf swarm. Follow your prompt exactly.",
        backstory="Research agent in a strict paper-trading pipeline. Output format discipline is mandatory.",
        verbose=False,
        allow_delegation=False,
        max_iter=8,
        llm=cfg.as_crewai_llm(),
        tools=list(UW_TOOLS),
    )


def _run(stage: str, day: date, description: str, agent: Agent) -> str:
    task = Task(description=description, expected_output="the exact mandated output block, nothing else", agent=agent)
    out = Crew(agents=[agent], tasks=[task], process=Process.sequential, verbose=False).kickoff()
    text = getattr(out, "raw", "") or str(out)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{day.isoformat()}_{stage}.txt").write_text(text)
    return text


KICKOFF_ATTEMPTS = 3


def _kickoff(build: Callable[[], Crew]) -> object:
    """Crew kickoff with retry. The LLM provider intermittently returns an
    empty completion, which CrewAI raises as ValueError("Invalid response
    from LLM call - None or empty.") — one empty response must not abort a
    whole scan. A fresh Crew object is built per attempt (task/agent objects
    may carry state from the failed run)."""
    for attempt in range(1, KICKOFF_ATTEMPTS + 1):
        try:
            return build().kickoff()
        except ValueError as e:
            transient = "None or empty" in str(e)
            if not transient or attempt == KICKOFF_ATTEMPTS:
                raise
            print(f"[retry] crew kickoff attempt {attempt}/{KICKOFF_ATTEMPTS} "
                  f"returned an empty LLM response, retrying", file=sys.stderr)
            time.sleep(2)


def _extract_candidates(scout_text: str) -> list[str]:
    tickers = []
    for m in re.finditer(r"^\s*(\d)\.\s*([A-Z]{1,5})\b", scout_text, re.M):
        t = m.group(2)
        if t not in tickers:
            tickers.append(t)
    return tickers[:MAX_CANDIDATES]


def _extract_specs(chair_text: str) -> tuple[list[dict], str]:
    specs, bad, empty_day = [], 0, False
    for m in re.finditer(r"```json\s*(\{.*?\})\s*```", chair_text, re.S):
        blob = m.group(1)
        try:
            obj = json.loads(blob)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(obj, dict) and "trade_id" not in obj and "specs" in obj:
            empty_day = True  # chair's empty-day object; never a spec
        else:
            specs.append(obj)
    if not specs and not empty_day:  # fallback: bare JSON objects
        for m in re.finditer(r"\{[^{}]*\"trade_id\"[^{}]*\}", chair_text, re.S):
            try:
                specs.append(json.loads(m.group(0)))
            except json.JSONDecodeError:
                bad += 1
    if bad:
        (RAW_DIR.parent / "parse_warnings.log").touch(exist_ok=True)
    return specs, empty_day


def run_scan(day: date | None = None) -> dict:
    day = day or date.today()
    if day.weekday() >= 5:
        return {"specs": [], "summary": "Weekend — no scan.", "date": day.isoformat()}

    tool_hint = TOOL_HINT
    # Stage A: regime -> scout (sequential chaining inside one crew)
    regime_agent = _agent("regime_analyst")
    regime_task = Task(
        description=prompts.load("regime_analyst") + tool_hint + f"\nScan date: {day.isoformat()}",
        expected_output="the exact mandated regime brief block",
        agent=regime_agent,
    )
    scout_agent = _agent("flow_scout")
    scout_task = Task(
        description=prompts.load("flow_scout") + tool_hint + "\nUse ONLY the regime brief from the previous task as context. The prompt's AT MOST 8 candidates cap governs.",
        expected_output="the exact mandated CANDIDATES block",
        agent=scout_agent,
        context=[regime_task],
    )
    _kickoff(lambda: Crew(agents=[regime_agent, scout_agent], tasks=[regime_task, scout_task],
                          process=Process.sequential, verbose=False))
    regime_text = str(regime_task.output.raw if regime_task.output else "")
    scout_text = str(scout_task.output.raw if scout_task.output else "")
    for stage, text in [("regime", regime_text), ("scout", scout_text)]:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"{day.isoformat()}_{stage}.txt").write_text(text)

    candidates = _extract_candidates(scout_text)
    dossiers_and_skeptics = []
    for rank, ticker in enumerate(candidates, 1):
        dossier_agent = _agent("dossier_analyst")
        d_task = Task(
            description=(prompts.load("dossier_analyst") + tool_hint +
                         f"\nAssigned TICKER: {ticker} (rank {rank}). Regime brief:\n{regime_text}"),
            expected_output="the exact mandated DOSSIER block",
            agent=dossier_agent,
        )
        skeptic_agent = _agent("skeptic")
        s_task = Task(
            description=prompts.load("skeptic") + f"\nAssigned TICKER: {ticker}. Verify the dossier from the previous task. Do not re-run the full list of tools — at most 2 verification calls.",
            expected_output="the exact mandated SKEPTIC block",
            agent=skeptic_agent,
            context=[d_task],
        )
        _kickoff(lambda: Crew(agents=[dossier_agent, skeptic_agent], tasks=[d_task, s_task],
                              process=Process.sequential, verbose=False))
        d_text = str(d_task.output.raw if d_task.output else "")
        s_text = str(s_task.output.raw if s_task.output else "")
        for stage, text in [(f"dossier_{rank}_{ticker}", d_text), (f"skeptic_{rank}_{ticker}", s_text)]:
            (RAW_DIR / f"{day.isoformat()}_{stage}.txt").write_text(text)
        dossiers_and_skeptics.append(f"### Candidate {rank}: {ticker}\nDOSSIER:\n{d_text}\nSKEPTIC:\n{s_text}\n")

    # Stage C: chair (learning loop may raise the chair's confidence bar)
    calibration = chair_calibration()
    chair_agent = _agent("chair")
    chair_desc = (prompts.load("chair") +
                  f"\nScan date: {day.isoformat()}\n\nREGIME BRIEF:\n{regime_text}\n\n"
                  f"SCOUT OUTPUT:\n{scout_text}\n\nPER-CANDIDATE PACKAGES:\n" +
                  "\n".join(dossiers_and_skeptics) +
                  "\n\nOutput ONLY the JSON specs (or the empty-day object).")
    if calibration:
        chair_desc += "\n\n" + calibration
    chair_task = Task(
        description=chair_desc,
        expected_output="JSON TradeSpec objects exactly per schema, or the empty-day JSON",
        agent=chair_agent,
    )
    _kickoff(lambda: Crew(agents=[chair_agent], tasks=[chair_task], process=Process.sequential,
                          verbose=False))
    chair_text = str(chair_task.output.raw if chair_task.output else "")
    (RAW_DIR / f"{day.isoformat()}_chair.txt").write_text(chair_text)

    specs, empty_day = _extract_specs(chair_text)
    if not specs and not empty_day:
        RAW_DIR.parent.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"{day.isoformat()}_parse_warning.txt").write_text(
            f"Chair output yielded 0 parseable specs and no empty-day object.\n---\n{chair_text}")
    specstore.save_merged(specs)  # ungated merge first: a gate crash must not lose the scan

    from swarm.backtest.gate import gate_spec
    from swarm.tools.uw import UWMCPClient
    gated = []
    if specs:
        uw = UWMCPClient()
        uw.initialize()
        for sp in specs:
            try:
                gated.append(gate_spec(sp, uw))
            except Exception as e:  # gate failure must not kill the scan
                sp = dict(sp)
                sp["backtest_gate"] = "pending_backtest"
                sp["gate_error"] = str(e)[:200]
                gated.append(sp)
        specstore.save_merged(gated)  # same trade_ids replace the ungated versions above

    matches = re.findall(r'"summary"\s*:\s*"([^"]+)"', chair_text)
    summary = matches[-1] if matches else chair_text[:300]
    return {"date": day.isoformat(), "candidates": candidates, "n_specs": len(gated),
            "specs": gated, "empty_day": empty_day and not specs, "summary": summary}


def main(argv: list[str]) -> int:
    """Scan-only CLI: run the crew pipeline for a date, persist merged specs.

      ./.venv/bin/python -m swarm.crew              # scan for today
      ./.venv/bin/python -m swarm.crew 2026-11-05   # scan stamped with an explicit date

    No fills, no marking — use swarm.daily for the full flow.
    """
    day = None
    if argv:
        try:
            day = date.fromisoformat(argv[0])
        except ValueError:
            print(f"bad date (use YYYY-MM-DD): {argv[0]}", file=sys.stderr)
            return 2
    scan = run_scan(day)
    print(json.dumps({
        "date": scan.get("date"),
        **{k: scan.get(k) for k in ("candidates", "n_specs", "empty_day", "summary")},
        "total_specs": len(specstore.load_existing()),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
