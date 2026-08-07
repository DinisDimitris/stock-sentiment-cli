"""
Rich terminal output formatter for investment summary.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text

console = Console()


def _direction_colour(direction: str) -> str:
    return {
        "BULLISH": "green",
        "BEARISH": "red",
        "NEUTRAL": "yellow",
        "MIXED": "cyan",
    }.get(direction, "white")


def _score_bar(score: float | None, width: int = 10) -> str:
    if score is None:
        return "no data"
    # Map [-1, 1] to [0, width]
    filled = round((score + 1) / 2 * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)


def _format_score(score: float | None) -> str:
    if score is None:
        return "  N/A    "
    sign = "+" if score >= 0 else ""
    return f"{sign}{score:.2f}"


def _importance_colour(importance: str) -> str:
    return {"CRITICAL": "red", "HIGH": "dark_orange", "MEDIUM": "yellow", "LOW": "dim"}.get(importance, "white")


def render_summary(result: dict[str, Any]) -> None:
    ticker = result.get("ticker", "?")
    company_name = result.get("company_name", ticker)
    sector = result.get("sector", "Unknown")
    direction = result.get("direction", "NEUTRAL")
    confidence = result.get("confidence_pct", 0)
    summary = result.get("summary", "")
    drivers = result.get("primary_drivers", [])
    risks = result.get("primary_risks", [])
    conflicts = result.get("conflicts", [])
    top_events = result.get("top_events", [])
    source_breakdown = result.get("source_breakdown", {})
    macro = result.get("macro_overlay", {})
    viral_alert = result.get("viral_alert", False)
    doc_count = result.get("document_count_7d", 0)
    generated_at = result.get("generated_at", "")
    from_cache = result.get("_from_cache", False)
    cache_expires = result.get("_expires_at", "")

    now_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M ET")

    # Header panel
    dir_color = _direction_colour(direction)
    header = f"[bold]{ticker}[/bold]  ({company_name}) | {sector}\n"
    header += f"Generated: {now_str}"
    console.print(Panel(header, title="[bold cyan]INVESTMENT SENTIMENT ANALYSIS[/bold cyan]", box=box.DOUBLE))

    # Direction + confidence
    console.print(f"\n[bold]DIRECTION:[/bold] [{dir_color} bold]{direction}[/{dir_color} bold]   "
                  f"[dim]Confidence: {confidence}%[/dim]")

    # Composite scores
    console.print("\n[bold]COMPOSITE SCORES[/bold]")
    score_1d = result.get("composite_score_1d")
    score_7d = result.get("composite_score_7d")
    score_30d = result.get("composite_score_30d")
    trend = result.get("trend", "unknown")
    console.print(f"  1-Day  : {_format_score(score_1d)}  {_score_bar(score_1d)}")
    console.print(f"  7-Day  : {_format_score(score_7d)}  {_score_bar(score_7d)}  [{trend}]")
    console.print(f"  30-Day : {_format_score(score_30d)}  {_score_bar(score_30d)}")
    macro_score = macro.get("score", 0)
    macro_desc = macro.get("description", "")
    console.print(f"  Macro  : {_format_score(macro_score)}  ({macro_desc})")

    # Events
    if top_events:
        console.print(f"\n[bold]MATERIAL EVENTS[/bold] (7-day window, {doc_count} total documents)")
        for ev in top_events[:5]:
            imp = ev.get("importance", "MEDIUM")
            color = _importance_colour(imp)
            score_str = f"  Sentiment: {_format_score(ev.get('score'))}" if ev.get("score") is not None else ""
            console.print(f"  [{color}][{imp}][/{color}] {ev.get('date', '')}  "
                          f"[dim]{ev.get('type', '')}[/dim]")
            console.print(f"    {ev.get('headline', '')}{score_str}")

    # Source breakdown
    if source_breakdown:
        console.print("\n[bold]SOURCE BREAKDOWN[/bold]")
        tier_labels = {
            "tier_1": ("Tier 1 — SEC Filings", 1.00),
            "tier_2": ("Tier 2 — Executive Comms", 0.85),
            "tier_3": ("Tier 3 — Financial News", 0.70),
            "tier_4": ("Tier 4 — Social Media", 0.45),
            "tier_5": ("Tier 5 — WallStreetBets", 0.25),
        }
        for key, (label, weight) in tier_labels.items():
            if key in source_breakdown:
                info = source_breakdown[key]
                sc = info.get("score")
                cnt = info.get("count", 0)
                note = "  [dim]*low confidence*[/dim]" if key in ("tier_4", "tier_5") else ""
                console.print(f"  {label:<28}: {_format_score(sc)}  ({cnt} docs, weight {weight:.2f}){note}")

    if viral_alert:
        console.print("\n  [bold red]! Reddit volume significantly above 30-day average — possible retail momentum event[/bold red]")

    # Conflicts / Risks
    if conflicts:
        console.print("\n[bold]CONFLICTS / RISKS DETECTED[/bold]")
        for i, c in enumerate(conflicts, 1):
            sev = c.get("severity", "MEDIUM")
            color = _importance_colour(sev)
            console.print(f"  {i}. [{color}]{sev}[/{color}]: {c.get('description', '')}")

    # Agent summary
    if summary:
        model_label = f"[dim]{settings_model_label(from_cache, cache_expires)}[/dim]"
        console.print(f"\n[bold]AGENT ASSESSMENT[/bold]  {model_label}")
        console.print(Panel(
            f'"{summary}"\n\n'
            f'[bold]Primary drivers:[/bold] {", ".join(drivers)}\n'
            f'[bold]Primary risks:[/bold] {", ".join(risks)}',
            box=box.SIMPLE,
        ))

    # Footer
    console.print(f"\n[dim]Data coverage: {doc_count} docs (7-day) | "
                  f"[italic]Algorithmic analysis only — not financial advice.[/italic][/dim]")
    console.rule()


def settings_model_label(from_cache: bool, expires_at: str) -> str:
    if from_cache and expires_at:
        return f"GPT-4o-mini | cached, expires {expires_at[:16]}"
    return "GPT-4o-mini | fresh analysis"
