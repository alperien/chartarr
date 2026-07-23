"""Terminal prettiness: banner, summaries, and the end-of-run stats panel."""
from __future__ import annotations

import re
from collections import Counter

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

BLOCKS = "▁▂▃▄▅▆▇█"


def banner() -> None:
    console.print()
    console.print("[bold magenta]  chartarr[/] [dim]♪  charts in, albums monitored[/]")
    console.print()


def rule(title: str) -> None:
    console.rule(f"[bold]{title}[/]", style="magenta")


def error(msg: str) -> None:
    console.print(f"[bold red]✗[/] {msg}")


def ok(msg: str) -> None:
    console.print(f"[bold green]✓[/] {msg}")


def match_summary(counts: Counter) -> None:
    total = sum(counts.values()) or 1
    t = Table.grid(padding=(0, 2))
    t.add_row("[bold green]matched[/]", f"{counts.get('matched', 0)}",
              f"[dim]{counts.get('matched', 0) / total:.0%}[/]")
    t.add_row("[bold yellow]review[/]", f"{counts.get('review', 0)}", "")
    t.add_row("[bold red]not found[/]", f"{counts.get('not_found', 0)}", "")
    console.print(Panel(t, title="matching", border_style="magenta", expand=False))


def push_summary(counts: Counter) -> None:
    t = Table.grid(padding=(0, 2))
    t.add_row("[bold green]added[/]", str(counts.get("added", 0)))
    t.add_row("[bold cyan]newly monitored[/]", str(counts.get("monitored", 0)))
    t.add_row("[dim]already there[/]", str(counts.get("skipped", 0)))
    if counts.get("failed"):
        t.add_row("[bold red]failed[/]", str(counts["failed"]))
    console.print(Panel(t, title="lidarr", border_style="magenta", expand=False))


def _year(value: str) -> int | None:
    m = re.search(r"\b(18|19|20)\d{2}\b", value or "")
    return int(m.group(0)) if m else None


def sparkline(counts: dict[int, int]) -> str:
    if not counts:
        return ""
    top = max(counts.values())
    lo, hi = min(counts), max(counts)
    decades = range(lo, hi + 10, 10)
    return "".join(BLOCKS[max(0, round((counts.get(d, 0) / top) * (len(BLOCKS) - 1)))]
                   for d in decades)


def stats_panel(rows: list[dict], artist_col: str, title_col: str) -> None:
    """Fun aggregates from whatever columns the CSV happens to have."""
    if not rows:
        return
    lines = Text()
    artists = {r[artist_col].split("\n")[0].strip() for r in rows}
    lines.append(f"{len(rows)} albums · {len(artists)} artists\n", style="bold")

    years = [y for r in rows for y in [_year(r.get("release_date") or r.get("year") or "")] if y]
    if years:
        decades = Counter((y // 10) * 10 for y in years)
        lo, hi = min(decades), max(decades)
        lines.append(f"{min(years)}–{max(years)}  ")
        lines.append(sparkline(decades), style="magenta")
        lines.append(f"  ({lo}s→{hi}s)\n", style="dim")
        oldest = min((r for r in rows if _year(r.get("release_date") or r.get("year") or "")),
                     key=lambda r: _year(r.get("release_date") or r.get("year") or ""))
        lines.append("oldest  ", style="dim")
        lines.append(f"{oldest[artist_col].splitlines()[0]} — "
                     f"{oldest[title_col].splitlines()[0]}\n")

    genres = Counter(g.strip() for r in rows
                     for g in (r.get("genres") or "").split(",") if g.strip())
    if genres:
        top3 = " · ".join(f"{g}" for g, _ in genres.most_common(3))
        lines.append("genres  ", style="dim")
        lines.append(top3 + "\n")

    console.print(Panel(lines, title="your chart", border_style="cyan", expand=False))
