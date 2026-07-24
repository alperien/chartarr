"""chartarr — feed your album charts to Lidarr.

Pipeline: match (MusicBrainz) → review (you) → push (Lidarr).
Every stage is resumable; state lives in <csv>.chartarr.jsonl next to your file.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

from rich.progress import (BarColumn, MofNCompleteColumn, Progress,
                           SpinnerColumn, TextColumn, TimeRemainingColumn)
from rich.prompt import Prompt

from . import __version__, lidarr, matcher, review, ui
from .ui import console

ARTIST_COLS = ("artist", "artists", "artist_name", "albumartist", "album artist")
TITLE_COLS = ("title", "album", "album_title", "release", "name")


# -------------------------------------------------------------------- config

def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))
    return Path(base) / "chartarr" / "config.json"


def load_config() -> dict:
    cfg = {}
    p = config_path()
    if p.exists():
        try:
            cfg = json.loads(p.read_text())
        except json.JSONDecodeError:
            pass
    url = os.environ.get("CHARTARR_LIDARR_URL") or os.environ.get("LIDARR_URL")
    key = os.environ.get("CHARTARR_API_KEY") or os.environ.get("LIDARR_API_KEY")
    if url:
        cfg["lidarr_url"] = url
    if key:
        cfg["api_key"] = key
    return cfg


def setup_wizard(existing: dict) -> dict:
    ui.rule("setup")
    console.print("[dim]stored in[/]", str(config_path()))
    url = Prompt.ask("Lidarr URL", default=existing.get("lidarr_url", "http://localhost:8686"))
    key = Prompt.ask("API key [dim](Settings → General → Security)[/]",
                     default=existing.get("api_key", ""))
    api = lidarr.Lidarr(url, key)
    try:
        status = api.status()
        ui.ok(f"connected to Lidarr {status.get('version', '')}")
    except lidarr.LidarrError as e:
        ui.error(str(e))
        if Prompt.ask("save anyway?", choices=["y", "n"], default="n") == "n":
            sys.exit(1)
    cfg = {"lidarr_url": url, "api_key": key}
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2) + "\n")
    try:
        p.chmod(0o600)
    except OSError:
        pass
    return cfg


# --------------------------------------------------------------------- state

class State:
    """Append-only event log: match results and review decisions by row key."""

    def __init__(self, path: Path):
        self.path = path
        self.results: dict[str, dict] = {}
        self.decisions: dict[str, dict] = {}
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("type") == "decision":
                        self.decisions[rec["key"]] = rec["decision"]
                    else:
                        self.results[rec["key"]] = rec

    def _append(self, rec: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def add_result(self, key: str, result: dict) -> None:
        result = {"key": key, **result}
        self.results[key] = result
        self._append(result)

    def add_decision(self, key: str, decision: dict) -> None:
        self.decisions[key] = decision
        self._append({"type": "decision", "key": key, "decision": decision})


# ----------------------------------------------------------------------- csv

def load_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        cols = reader.fieldnames or []
    if not rows:
        ui.error(f"{path} has no data rows")
        sys.exit(1)
    lookup = {c.lower().strip(): c for c in cols}
    artist_col = next((lookup[c] for c in ARTIST_COLS if c in lookup), None)
    title_col = next((lookup[c] for c in TITLE_COLS if c in lookup), None)
    if not artist_col or not title_col:
        ui.error(f"couldn't find artist/title columns in: {', '.join(cols)}")
        console.print(f"[dim]accepted artist columns: {', '.join(ARTIST_COLS)}[/]")
        console.print(f"[dim]accepted title columns:  {', '.join(TITLE_COLS)}[/]")
        sys.exit(1)
    rows = [r for r in rows if (r.get(artist_col) or "").strip()
            and (r.get(title_col) or "").strip()]
    key_col = lookup.get("rank") or lookup.get("id")
    for i, r in enumerate(rows, 1):
        r["_key"] = str(r[key_col]) if key_col and r.get(key_col) else f"row{i}"
    return rows, artist_col, title_col


# -------------------------------------------------------------------- stages

def stage_match(rows, artist_col, title_col, state: State) -> None:
    pending = [r for r in rows if r["_key"] not in state.results]
    if not pending:
        ui.ok("matching already complete (delete the .chartarr.jsonl file to redo)")
        return
    ui.rule(f"matching {len(pending)} albums against MusicBrainz")
    console.print("[dim]~1/sec — MusicBrainz rate limit. Ctrl+C anytime; it resumes.[/]")
    counts = Counter(r["status"] for r in state.results.values())
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(),
                  MofNCompleteColumn(), TimeRemainingColumn(),
                  console=console) as prog:
        task = prog.add_task("warming up…", total=len(pending))
        for row, result in matcher.iter_match(pending, artist_col, title_col):
            state.add_result(row["_key"], result)
            counts[result["status"]] += 1
            done = sum(counts.values())
            pct = counts.get("matched", 0) / done if done else 0
            name = f"{row[artist_col].splitlines()[0][:24]} — {row[title_col].splitlines()[0][:28]}"
            prog.update(task, advance=1,
                        description=f"[bold]{pct:.0%}[/] auto-matched · ♪ {name}")
    ui.match_summary(counts)


def stage_review(rows, artist_col, title_col, state: State) -> None:
    by_key = {r["_key"]: r for r in rows}
    pending = [(by_key[k], res) for k, res in state.results.items()
               if res["status"] in ("review", "not_found")
               and k not in state.decisions and k in by_key]
    if not pending:
        return
    ui.rule(f"review — {len(pending)} uncertain matches")
    decisions = review.run_review(pending, artist_col, title_col)
    for key, decision in decisions.items():
        state.add_decision(key, decision)


def import_set(rows, state: State) -> list[dict]:
    by_key = {r["_key"]: r for r in rows}
    out = []
    for key, res in state.results.items():
        row = by_key.get(key)
        if row is None:
            continue
        if res["status"] == "matched":
            out.append({"key": key, "row": row, "rgid": res["release_group_mbid"]})
        else:
            d = state.decisions.get(key)
            if d and d.get("action") == "accept":
                out.append({"key": key, "row": row, "rgid": d["mbid"]})
    return out


def _pick(items, wanted, label, key="name"):
    if not items:
        raise lidarr.LidarrError(f"no {label}s configured in Lidarr — create one first")
    if wanted:
        for it in items:
            if it[key].lower() == wanted.lower():
                return it
        names = ", ".join(i[key] for i in items)
        raise lidarr.LidarrError(f"{label} '{wanted}' not found (available: {names})")
    return items[0]


def stage_push(items, artist_col, title_col, args, cfg) -> None:
    if not items:
        ui.error("nothing to push — no matched albums yet")
        return
    ui.rule(f"pushing {len(items)} albums to Lidarr")
    if args.dry_run:
        for it in items[:15]:
            row = it["row"]
            console.print(f"  [green]would add[/] "
                          f"{row[artist_col].splitlines()[0]} — {row[title_col].splitlines()[0]}")
        if len(items) > 15:
            console.print(f"  [dim]… and {len(items) - 15} more[/]")
        ui.ok("dry run — nothing sent")
        return

    api = lidarr.Lidarr(cfg["lidarr_url"], cfg["api_key"])
    status = api.status()
    ui.ok(f"Lidarr {status.get('version', '')}")
    qp = _pick(api.quality_profiles(), args.quality_profile, "quality profile")
    mp = _pick(api.metadata_profiles(), args.metadata_profile, "metadata profile")
    rf = _pick(api.root_folders(), args.root_folder, "root folder", key="path")
    console.print(f"[dim]profile {qp['name']} · metadata {mp['name']} · root {rf['path']}[/]")

    counts: Counter = Counter()
    failures: list[str] = []
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), BarColumn(),
                  MofNCompleteColumn(), console=console) as prog:
        task = prog.add_task("pushing…", total=len(items))
        for it in items:
            row = it["row"]
            label = f"{row[artist_col].splitlines()[0][:24]} — {row[title_col].splitlines()[0][:28]}"
            try:
                outcome = api.add_album(it["rgid"], qp["id"], mp["id"], rf["path"],
                                        search=args.search)
                counts[outcome] += 1
            except lidarr.LidarrError as e:
                counts["failed"] += 1
                failures.append(f"{label}: {e}")
            prog.update(task, advance=1, description=f"♪ {label}")

    ui.push_summary(counts)
    for f in failures[:10]:
        console.print(f"  [red]✗[/] {f}")
    if len(failures) > 10:
        console.print(f"  [dim]… and {len(failures) - 10} more failures[/]")


# ---------------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chartarr",
        description="Feed your album charts to Lidarr: match a CSV of albums "
                    "against MusicBrainz, review the uncertain ones, and add "
                    "everything as monitored albums.")
    p.add_argument("csv", nargs="?", help="CSV with artist and title/album columns")
    p.add_argument("--setup", action="store_true", help="configure Lidarr URL + API key")
    stage = p.add_mutually_exclusive_group()
    stage.add_argument("--match-only", action="store_true", help="stop after matching")
    stage.add_argument("--review-only", action="store_true", help="only run the review TUI")
    stage.add_argument("--push-only", action="store_true", help="only push to Lidarr")
    p.add_argument("--yes", "-y", action="store_true", help="skip review, push matched only")
    p.add_argument("--dry-run", action="store_true", help="show what would be pushed")
    p.add_argument("--search", action="store_true", help="tell Lidarr to search for added albums")
    p.add_argument("--quality-profile", help="Lidarr quality profile name (default: first)")
    p.add_argument("--metadata-profile", help="Lidarr metadata profile name (default: first)")
    p.add_argument("--root-folder", help="Lidarr root folder path (default: first)")
    p.add_argument("--state", help="state file path (default: <csv>.chartarr.jsonl)")
    p.add_argument("--version", action="version", version=f"chartarr {__version__}")
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    ui.banner()

    cfg = load_config()
    if args.setup:
        cfg = setup_wizard(cfg)
        if not args.csv:
            return
    if not args.csv:
        build_parser().print_help()
        return

    csv_path = Path(args.csv)
    if not csv_path.exists():
        ui.error(f"no such file: {csv_path}")
        sys.exit(1)
    rows, artist_col, title_col = load_csv(csv_path)
    console.print(f"[dim]{csv_path.name}: {len(rows)} albums "
                  f"(artist: {artist_col!r}, title: {title_col!r})[/]")

    state = State(Path(args.state) if args.state else
                  csv_path.with_suffix(csv_path.suffix + ".chartarr.jsonl"))

    needs_push = not (args.match_only or args.review_only)
    if needs_push and not args.dry_run and not (cfg.get("lidarr_url") and cfg.get("api_key")):
        console.print("[yellow]![/] no Lidarr config yet — quick setup first")
        cfg = setup_wizard(cfg)

    try:
        if not (args.review_only or args.push_only):
            stage_match(rows, artist_col, title_col, state)
        if not (args.match_only or args.push_only or args.yes):
            stage_review(rows, artist_col, title_col, state)
        if needs_push:
            items = import_set(rows, state)
            stage_push(items, artist_col, title_col, args, cfg)
            pushed_rows = [it["row"] for it in items]
            ui.stats_panel(pushed_rows, artist_col, title_col)
    except KeyboardInterrupt:
        console.print("\n[dim]interrupted — progress saved, run the same command to resume[/]")
        sys.exit(130)


if __name__ == "__main__":
    main()
