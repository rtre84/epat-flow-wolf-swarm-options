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
from datetime import date
from pathlib import Path

from crewai import Agent, Crew, Process, Task

from swarm.llm import LLMConfig
from swarm import prompts
from swarm.tools.uw_tools import UW_TOOLS

RAW_DIR = Path(__file__).resolve().parent.parent / "reports" / "raw"
SPEC_FILE = Path(__file__).resolve().parent.parent / "data" / "specs" / "trade_specs.json"
MAX_CANDIDATES = 5

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
        description=prompts.load("flow_scout") + tool_hint + "\nUse ONLY the regime brief from the previous task as context. Keep it to 3 candidates for cost discipline unless the tape is exceptional.",
        expected_output="the exact mandated CANDIDATES block with at most 3 ranked candidates",
        agent=scout_agent,
        context=[regime_task],
    )
    stage_a = Crew(agents=[regime_agent, scout_agent], tasks=[regime_task, scout_task],
                   process=Process.sequential, verbose=False).kickoff()
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
        sub = Crew(agents=[dossier_agent, skeptic_agent], tasks=[d_task, s_task],
                   process=Process.sequential, verbose=False).kickoff()
        d_text = str(d_task.output.raw if d_task.output else "")
        s_text = str(s_task.output.raw if s_task.output else "")
        for stage, text in [(f"dossier_{rank}_{ticker}", d_text), (f"skeptic_{rank}_{ticker}", s_text)]:
            (RAW_DIR / f"{day.isoformat()}_{stage}.txt").write_text(text)
        dossiers_and_skeptics.append(f"### Candidate {rank}: {ticker}\nDOSSIER:\n{d_text}\nSKEPTIC:\n{s_text}\n")

    # Stage C: chair
    chair_agent = _agent("chair")
    chair_task = Task(
        description=(prompts.load("chair") +
                     f"\nScan date: {day.isoformat()}\n\nREGIME BRIEF:\n{regime_text}\n\n"
                     f"SCOUT OUTPUT:\n{scout_text}\n\nPER-CANDIDATE PACKAGES:\n" +
                     "\n".join(dossiers_and_skeptics) +
                     "\n\nOutput ONLY the JSON specs (or the empty-day object)."),
        expected_output="JSON TradeSpec objects exactly per schema, or the empty-day JSON",
        agent=chair_agent,
    )
    chair_out = Crew(agents=[chair_agent], tasks=[chair_task], process=Process.sequential,
                     verbose=False).kickoff()
    chair_text = str(chair_task.output.raw if chair_task.output else "")
    (RAW_DIR / f"{day.isoformat()}_chair.txt").write_text(chair_text)

    specs, empty_day = _extract_specs(chair_text)
    if not specs and not empty_day:
        RAW_DIR.parent.mkdir(parents=True, exist_ok=True)
        (RAW_DIR / f"{day.isoformat()}_parse_warning.txt").write_text(
            f"Chair output yielded 0 parseable specs and no empty-day object.\n---\n{chair_text}")
    SPEC_FILE.parent.mkdir(parents=True, exist_ok=True)
    SPEC_FILE.write_text(json.dumps(specs, indent=2))
    matches = re.findall(r'"summary"\s*:\s*"([^"]+)"', chair_text)
    summary = matches[-1] if matches else chair_text[:300]
    return {"date": day.isoformat(), "candidates": candidates, "n_specs": len(specs),
            "specs": specs, "empty_day": empty_day and not specs, "summary": summary}
