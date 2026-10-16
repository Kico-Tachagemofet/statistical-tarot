"""Three explicit operations: draw once, analyze saved raw data, or render JSON."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .core import (MAX_DRAWS, RunError, analyze_run, draw_run, read_json,
                   validate_draws, validate_statistics)


def _draw_count(text: str) -> int:
    try:
        return validate_draws(int(text))
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(f"draws must be an integer from 1 to {MAX_DRAWS}") from exc


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="statistical-tarot",
        description="Local five-pile tarot sampling and descriptive statistics. Only 'draw' consumes randomness.",
    )
    sub = result.add_subparsers(dest="command", required=True)
    draw = sub.add_parser("draw", help="Start one fixed-size run in a NEW directory; never restart or resume.")
    draw.add_argument("--question", required=True, help="Question text to preserve verbatim (1–10000 characters).")
    draw.add_argument("--out", type=Path, required=True, help="New run directory; any existing directory is refused.")
    draw.add_argument("--draws", type=_draw_count, default=1000,
                      help=f"Fixed count, 1–{MAX_DRAWS} (default: 1000); no early stopping or continuation.")
    analyze = sub.add_parser("analyze", help="Verify completed raw data and rebuild statistics.json + page.html; no randomness.")
    analyze.add_argument("--input", type=Path, required=True,
                         help="Run directory containing protocol.json, raw.ndjson and a valid completed receipt.json.")
    render = sub.add_parser("render", help="Render saved statistics as page.html; no sampling or recomputation.")
    render.add_argument("--input", type=Path, required=True, help="Path to a statistics.json file.")
    render.add_argument("--out", type=Path, required=True, help="Report directory; only page.html is created/replaced.")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    try:
        # Rendering is imported only after argument parsing; --help needs no UI.
        from .report import write_page
        if args.command == "draw":
            draw_run(args.question, args.out, args.draws)
            print(f"Draw records completed and saved: {args.out}")
            print("If report generation fails, use 'analyze' on this saved run; do not draw again.")
            stats = analyze_run(args.out)
            write_page(args.out, stats)
            print(f"Report: {args.out / 'page.html'}")
        elif args.command == "analyze":
            stats = analyze_run(args.input)
            write_page(args.input, stats)
            print(f"Verified {stats['actual_n']} saved records. Report: {args.input / 'page.html'}")
        else:
            stats = read_json(args.input)
            validate_statistics(stats)
            args.out.mkdir(parents=True, exist_ok=True)
            write_page(args.out, stats)
            print(f"Rendered existing statistics only: {args.out / 'page.html'}")
    except KeyboardInterrupt:
        print("Interrupted. Preserve the run directory; incomplete or uncertain draws cannot be resumed or redrawn.", file=sys.stderr)
        return 130
    except (RunError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0
