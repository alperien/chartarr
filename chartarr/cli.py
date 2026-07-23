"""chartarr - feed a csv of albums to lidarr."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

from . import __version__, demo, lidarr, matcher, review

ARTIST_COLS = ("artist", "artists", "artist_name", "albumartist", "album artist")
TITLE_COLS = ("title", "album", "album_title", "release", "name")

BLOCKS = "▁▂▃▄▅▆▇█"

EXAMPLE_CSV = """\
rank,title,artist,release_date,genres
1,OK Computer,Radiohead,16 June 1997,"Alternative Rock, Art Rock"
2,To Pimp a Butterfly,Kendrick Lamar,15 March 2015,"Conscious Hip Hop, Jazz Rap"
3,★ [Blackstar],David Bowie,8 January 2016,"Art Rock, Experimental Rock"
4,F♯A♯∞,Godspeed You Black Emperor!,14 August 1997,"Post-Rock"
5,Piñata,Freddie Gibbs & Madlib,18 March 2014,"Gangsta Rap, Abstract Hip Hop"
6,Ágætis byrjun,Sigur Rós,12 June 1999,"Post-Rock, Dream Pop"
7,Kind of Blue,Miles Davis,17 August 1959,"Modal Jazz, Cool Jazz"
8,Rumours,Fleetwood Mac,4 February 1977,"Pop Rock, Soft Rock"
9,Clube da esquina,Milton Nascimento & Lô Borges,March 1972,"MPB, Psychedelic Pop"
10,Spiderland,Slint,27 March 1991,"Post-Rock, Math Rock"
"""


# terminal

def _color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def accent(s) -> str:
    return f"\033[36m{s}\033[0m" if _color() else str(s)


def dim(s) -> str:
    return f"\033[2m{s}\033[0m" if _color() else str(s)


def status(line: str) -> None:
    # single updating line; silent when piped
    if not sys.stdout.isatty():
        return
    width = shutil.get_terminal_size().columns - 1
    sys.stdout.write("\r" + line[:width].ljust(width))
    sys.stdout.flush()


def status_end() -> None:
    if sys.stdout.isatty():
        sys.stdout.write("\r" + " " * (shutil.get_terminal_size().columns - 1) + "\r")
        sys.stdout.flush()


def fail(msg: str) -> None:
    print(f"chartarr: {msg}", file=sys.stderr)
    sys.exit(1)


# config

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
    default = existing.get("lidarr_url", "http://localhost:8686")
    url = input(f"lidarr url [{default}]: ").strip() or default
    key = input("api key (lidarr: settings > general > security): ").strip() \
        or existing.get("api_key", "")
    try:
        version = lidarr.Lidarr(url, key).status().get("version", "")
        print(dim(f"connected to lidarr {version}"))
    except lidarr.LidarrError as e:
        print(f"chartarr: {e}", file=sys.stderr)
        if input("save anyway? [y/N] ").strip().lower() != "y":
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


# state: append-only log of match results and review decisions

class State:
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
                        d = rec["decision"]
                        if d.get("action") == "clear":
                            self.decisions.pop(rec["key"], None)
                        else:
                            self.decisions[rec["key"]] = d
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
        if decision.get("action") == "clear":
            self.decisions.pop(key, None)
        else:
            self.decisions[key] = decision
        self._append({"type": "decision", "key": key, "decision": decision})


# csv

def load_csv(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        cols = reader.fieldnames or []
    if not rows:
        fail(f"{path} has no data rows")
    lookup = {c.lower().strip(): c for c in cols}
    artist_col = next((lookup[c] for c in ARTIST_COLS if c in lookup), None)
    title_col = next((lookup[c] for c in TITLE_COLS if c in lookup), None)
    if not artist_col or not title_col:
        fail(f"need an artist and a title/album column, found: {', '.join(cols)}")
    rows = [r for r in rows if (r.get(artist_col) or "").strip()
            and (r.get(title_col) or "").strip()]
    key_col = lookup.get("rank") or lookup.get("id")
    for i, r in enumerate(rows, 1):
        r["_key"] = str(r[key_col]) if key_col and r.get(key_col) else f"row{i}"
    return rows, artist_col, title_col


def _one_line(s: str) -> str:
    return s.splitlines()[0] if s else s


def _n(count: int, word: str) -> str:
    return f"{count} {word}" + ("" if count == 1 else "s")


# stages

def stage_match(rows, artist_col, title_col, state: State) -> None:
    pending = [r for r in rows if r["_key"] not in state.results]
    if not pending:
        print(dim("matching already done"))
        return
    mins = len(pending) * 1.1 / 60
    print(f"matching {_n(len(pending), 'album')} against musicbrainz "
          + dim(f"(about {max(1, round(mins))} min, ctrl-c resumes)"))
    counts = Counter(r["status"] for r in state.results.values())
    for i, (row, result) in enumerate(matcher.iter_match(pending, artist_col, title_col), 1):
        state.add_result(row["_key"], result)
        counts[result["status"]] += 1
        done = sum(counts.values())
        pct = counts.get("matched", 0) / done if done else 0
        status(f"  {i}/{len(pending)}  ok {pct:.0%}  "
               f"{_one_line(row[artist_col])} — {_one_line(row[title_col])}")
    status_end()
    print(f"matched {accent(counts.get('matched', 0))} · "
          f"review {accent(counts.get('review', 0))} · "
          f"not found {accent(counts.get('not_found', 0))}")


def stage_review(rows, artist_col, title_col, state: State) -> None:
    by_key = {r["_key"]: r for r in rows}
    pending = [(by_key[k], res) for k, res in state.results.items()
               if res["status"] in ("review", "not_found")
               and k not in state.decisions and k in by_key]
    if not pending:
        return
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print(dim(f"{len(pending)} rows need review — rerun in a terminal, "
                  f"or use --yes to push without them"))
        return
    review.run(pending, artist_col, title_col, state.add_decision)
    picked = sum(1 for _, res in pending
                 if state.decisions.get(res["key"], {}).get("action") == "accept")
    skipped = sum(1 for _, res in pending
                  if state.decisions.get(res["key"], {}).get("action") == "skip")
    left = len(pending) - picked - skipped
    print(f"review: {accent(picked)} picked · {accent(skipped)} skipped · "
          f"{accent(left)} left")


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
        raise lidarr.LidarrError(f"no {label} configured in lidarr")
    if wanted:
        for it in items:
            if it[key].lower() == wanted.lower():
                return it
        raise lidarr.LidarrError(
            f"{label} {wanted!r} not found (have: {', '.join(i[key] for i in items)})")
    return items[0]


def stage_push(items, artist_col, title_col, args, cfg) -> None:
    if not items:
        print(dim("nothing to push"))
        return
    if args.dry_run:
        print(f"would push {accent(_n(len(items), 'album'))} to lidarr:")
        for it in items[:12]:
            row = it["row"]
            print(f"  {_one_line(row[artist_col])} — {_one_line(row[title_col])}")
        if len(items) > 12:
            print(dim(f"  … and {len(items) - 12} more"))
        return

    api = lidarr.Lidarr(cfg["lidarr_url"], cfg["api_key"])
    api.status()
    qp = _pick(api.quality_profiles(), args.quality_profile, "quality profile")
    mp = _pick(api.metadata_profiles(), args.metadata_profile, "metadata profile")
    rf = _pick(api.root_folders(), args.root_folder, "root folder", key="path")
    print(f"pushing {_n(len(items), 'album')} to lidarr "
          + dim(f"({qp['name']}, {rf['path']})"))

    counts: Counter = Counter()
    failures = []
    for i, it in enumerate(items, 1):
        row = it["row"]
        name = f"{_one_line(row[artist_col])} — {_one_line(row[title_col])}"
        try:
            outcome = api.add_album(it["rgid"], qp["id"], mp["id"], rf["path"],
                                    search=args.search)
            counts[outcome] += 1
            status(f"  {i}/{len(items)}  {outcome}  {name}")
        except lidarr.LidarrError as e:
            counts["failed"] += 1
            failures.append(f"{name}: {e}")
    status_end()
    line = (f"added {accent(counts.get('added', 0))} · "
            f"monitored {accent(counts.get('monitored', 0))} · "
            f"already there {accent(counts.get('skipped', 0))}")
    if counts.get("failed"):
        line += f" · failed {accent(counts['failed'])}"
    print(line)
    for f_ in failures[:8]:
        print(dim(f"  {f_}"))
    if len(failures) > 8:
        print(dim(f"  … and {len(failures) - 8} more"))


def _year(value: str):
    m = re.search(r"\b(18|19|20)\d{2}\b", value or "")
    return int(m.group(0)) if m else None


def closing_line(rows, artist_col) -> None:
    artists = {_one_line(r[artist_col]).strip() for r in rows}
    parts = [f"{_n(len(rows), 'album')}, {_n(len(artists), 'artist')}"]
    years = [y for r in rows
             for y in [_year(r.get("release_date") or r.get("year") or "")] if y]
    if years:
        decades = Counter((y // 10) * 10 for y in years)
        top = max(decades.values())
        lo, hi = min(decades), max(decades)
        spark = "".join(
            BLOCKS[max(0, round(decades.get(d, 0) / top * (len(BLOCKS) - 1)))]
            for d in range(lo, hi + 10, 10))
        parts.append(f"{min(years)}–{max(years)} {spark}")
    genres = Counter(g.strip().lower() for r in rows
                     for g in (r.get("genres") or "").split(",") if g.strip())
    if genres:
        parts.append(f"mostly {genres.most_common(1)[0][0]}")
    print(dim(" · ".join(parts)))


# entry

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="chartarr",
        description="match a csv of albums to musicbrainz and add them to lidarr")
    p.add_argument("csv", nargs="?", help="csv with artist and title/album columns")
    p.add_argument("--setup", action="store_true", help="set lidarr url and api key")
    stage = p.add_mutually_exclusive_group()
    stage.add_argument("--match-only", action="store_true", help="stop after matching")
    stage.add_argument("--review-only", action="store_true", help="just the review screen")
    stage.add_argument("--push-only", action="store_true", help="just the push")
    p.add_argument("--yes", "-y", action="store_true", help="skip review")
    p.add_argument("--dry-run", action="store_true", help="show what would be pushed")
    p.add_argument("--search", action="store_true", help="have lidarr search for added albums")
    p.add_argument("--quality-profile", help="lidarr quality profile (default: first)")
    p.add_argument("--metadata-profile", help="lidarr metadata profile (default: first)")
    p.add_argument("--root-folder", help="lidarr root folder (default: first)")
    p.add_argument("--state", help="state file (default: <csv>.chartarr.jsonl)")
    p.add_argument("--example", action="store_true",
                   help="write sample.csv to the current directory")
    p.add_argument("--demo", action="store_true",
                   help="simulate a full run with sample data")
    p.add_argument("--version", action="version", version=f"chartarr {__version__}")
    return p


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)

    if args.example:
        p = Path("sample.csv")
        if p.exists():
            fail("sample.csv already exists here")
        p.write_text(EXAMPLE_CSV, encoding="utf-8")
        print("wrote sample.csv — try: chartarr sample.csv --dry-run")
        return

    if args.demo:
        demo.run()
        return

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
        fail(f"no such file: {csv_path}")
    rows, artist_col, title_col = load_csv(csv_path)
    print(dim(f"{csv_path.name}: {_n(len(rows), 'album')}"))

    state = State(Path(args.state) if args.state else
                  csv_path.with_suffix(csv_path.suffix + ".chartarr.jsonl"))

    needs_push = not (args.match_only or args.review_only)
    if needs_push and not args.dry_run and not (cfg.get("lidarr_url") and cfg.get("api_key")):
        cfg = setup_wizard(cfg)

    try:
        if not (args.review_only or args.push_only):
            stage_match(rows, artist_col, title_col, state)
        if not (args.match_only or args.push_only or args.yes):
            stage_review(rows, artist_col, title_col, state)
        if needs_push:
            items = import_set(rows, state)
            stage_push(items, artist_col, title_col, args, cfg)
            if items and not args.dry_run:
                closing_line([it["row"] for it in items], artist_col)
    except KeyboardInterrupt:
        status_end()
        print(dim("stopped — progress is saved, rerun to resume"))
        sys.exit(130)
    except lidarr.LidarrError as e:
        fail(str(e))


if __name__ == "__main__":
    main()
