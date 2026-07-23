"""The little review TUI: resolve uncertain matches with single keystrokes."""
from __future__ import annotations

import re
import sys
import webbrowser

from rich.panel import Panel
from rich.table import Table

from .ui import console

MBID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _getch() -> str:
    try:
        import msvcrt
        return msvcrt.getwch()
    except ImportError:
        import termios
        import tty
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if ch == "\x03":  # Ctrl+C
            raise KeyboardInterrupt
        return ch


def _card(row: dict, result: dict, artist_col: str, title_col: str,
          pos: int, total: int) -> Panel:
    cands = result.get("candidates") or []
    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold", no_wrap=True)
    t.add_column()

    t.add_row("[cyan]your chart[/]",
              f"{row[artist_col].splitlines()[0]} — {row[title_col].splitlines()[0]}")
    year = (row.get("release_date") or "")[:32]
    if year:
        t.add_row("", f"[dim]{year}[/]")
    t.add_row("", "")

    if not cands:
        t.add_row("[red]no candidates[/]", "[dim]MusicBrainz search came up empty[/]")
    for i, c in enumerate(cands, 1):
        types = c.get("mb_primary_type") or "?"
        if c.get("mb_secondary_types"):
            types += f" / {c['mb_secondary_types']}"
        t.add_row(
            f"[magenta]{i}[/]",
            f"{c['mb_artist']} — {c['mb_title']}\n"
            f"[dim]{types} · {c.get('mb_first_release') or 'date?'} · "
            f"similarity {c['title_sim']:.2f}/{c['artist_sim']:.2f}[/]")

    return Panel(t, title=f"review {pos}/{total}",
                 subtitle="[dim]1-3 pick · s skip · o open in browser · m manual mbid · q save+quit[/]",
                 border_style="yellow", expand=False)


def run_review(pending: list[tuple[dict, dict]], artist_col: str,
               title_col: str) -> dict[str, dict]:
    """Walk uncertain rows; return {key: decision} decisions.

    decision is {"action": "accept", "mbid": ..., "artist_mbid": ...}
    or {"action": "skip"}.
    """
    if not sys.stdin.isatty():
        console.print("[yellow]![/] not an interactive terminal — skipping review "
                      "(run [bold]chartarr ... --review-only[/] later)")
        return {}

    decisions: dict[str, dict] = {}
    total = len(pending)
    accepted = skipped = 0

    for pos, (row, result) in enumerate(pending, 1):
        console.print(_card(row, result, artist_col, title_col, pos, total))
        cands = result.get("candidates") or []
        while True:
            key = _getch().lower()
            if key in "123" and int(key) <= len(cands):
                c = cands[int(key) - 1]
                decisions[result["key"]] = {"action": "accept",
                                            "mbid": c["release_group_mbid"],
                                            "artist_mbid": c.get("artist_mbid")}
                accepted += 1
                console.print(f"  [green]✓ {c['mb_artist']} — {c['mb_title']}[/]\n")
                break
            if key == "s":
                decisions[result["key"]] = {"action": "skip"}
                skipped += 1
                console.print("  [dim]skipped[/]\n")
                break
            if key == "o" and cands:
                webbrowser.open(
                    f"https://musicbrainz.org/release-group/{cands[0]['release_group_mbid']}")
                continue
            if key == "m":
                raw = console.input("  paste release-group MBID (or blank to cancel): ").strip()
                if not raw:
                    continue
                if not MBID_RE.match(raw):
                    console.print("  [red]that doesn't look like an MBID[/]")
                    continue
                decisions[result["key"]] = {"action": "accept", "mbid": raw,
                                            "artist_mbid": None}
                accepted += 1
                console.print("  [green]✓ manual[/]\n")
                break
            if key == "q":
                console.print(f"\n[dim]review paused — {accepted} accepted, "
                              f"{skipped} skipped, {total - pos} left for next time[/]")
                return decisions

    console.print(f"[bold]review done[/] — {accepted} accepted, {skipped} skipped")
    return decisions
