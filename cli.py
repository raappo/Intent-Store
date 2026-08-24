"""
cli.py — Intent-Store command-line interface.

Commands
────────
  scan   <dir>          Walk directory, embed files, score, and reason.
  rescore               Re-run scoring + reasoning on existing indexed files.
  report                Print a recommendations table.
  accept <path>         Accept a recommendation (boosts importance_score).
  reject <path>         Reject a recommendation (suppresses and penalises score).
"""

import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich import box

from scanner import get_connection, scan_directory, DB_PATH
from profiler import embed_all
from scorer import score_all
from reasoner import reason_all

console = Console()

# Feedback-loop weight applied on accept / reject
ACCEPT_BOOST  =  0.15
REJECT_PENALTY = 0.15

ACTION_STYLES = {
    "archive":  ("red",    "📦"),
    "compress": ("yellow", "🗜️"),
    "keep":     ("green",  "✅"),
}


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        format="%(levelname)s %(name)s: %(message)s",
        level=level,
    )


@click.group()
@click.option("--db", default=DB_PATH, show_default=True, help="Path to SQLite database.")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
@click.pass_context
def cli(ctx: click.Context, db: str, verbose: bool) -> None:
    """Intent-Store — Semantic storage intelligence for Linux."""
    ctx.ensure_object(dict)
    ctx.obj["db"] = db
    _setup_logging(verbose)


# ── scan ─────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--skip-embed", is_flag=True, help="Skip semantic embedding step.")
@click.option("--skip-reason", is_flag=True, help="Skip LLM reasoning step.")
@click.pass_context
def scan(ctx: click.Context, directory: str, skip_embed: bool, skip_reason: bool) -> None:
    """Scan DIRECTORY: index files, embed, score, and generate recommendations."""
    db = ctx.obj["db"]

    with console.status("[bold cyan]Scanning directory …"):
        n_files = scan_directory(directory, db_path=db)
    console.print(f"[green]✔[/green] Indexed [bold]{n_files}[/bold] files.")

    if not skip_embed:
        with console.status("[bold cyan]Generating semantic embeddings …"):
            n_embedded = embed_all(db_path=db)
        console.print(f"[green]✔[/green] Embedded [bold]{n_embedded}[/bold] files.")

    with console.status("[bold cyan]Scoring files …"):
        n_scored = score_all(db_path=db)
    console.print(f"[green]✔[/green] Scored [bold]{n_scored}[/bold] files.")

    if not skip_reason:
        with console.status("[bold cyan]Reasoning about candidates …"):
            n_reasoned = reason_all(db_path=db)
        console.print(f"[green]✔[/green] Generated recommendations for [bold]{n_reasoned}[/bold] files.")

    console.print(
        "\n[bold]Done.[/bold] Run [cyan]python3 cli.py report[/cyan] to see recommendations."
    )


# ── rescore ───────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--force", is_flag=True, help="Re-reason files that already have a recommendation.")
@click.pass_context
def rescore(ctx: click.Context, force: bool) -> None:
    """Re-run scoring and reasoning on already-indexed files.

    Use this after `demo_seed.py` (or any external timestamp update) to
    refresh scores and recommendations without re-scanning.
    """
    db = ctx.obj["db"]

    with console.status("[bold cyan]Re-scoring files …"):
        n_scored = score_all(db_path=db)
    console.print(f"[green]✔[/green] Re-scored [bold]{n_scored}[/bold] files.")

    with console.status("[bold cyan]Re-reasoning candidates …"):
        n_reasoned = reason_all(db_path=db, force=force)
    console.print(f"[green]✔[/green] Generated/refreshed [bold]{n_reasoned}[/bold] recommendations.")
    console.print(
        "\nRun [cyan]python3 cli.py report[/cyan] to view updated recommendations."
    )


# ── report ────────────────────────────────────────────────────────────────────

@cli.command()
@click.option("--all", "show_all", is_flag=True, help="Show all files, not just recommendations.")
@click.option("--limit", default=50, show_default=True, help="Max rows to display.")
@click.pass_context
def report(ctx: click.Context, show_all: bool, limit: int) -> None:
    """Display the current recommendation table."""
    db = ctx.obj["db"]
    conn = get_connection(db_path=db)

    if show_all:
        rows = conn.execute(
            "SELECT path, size, atime, mtime, importance_score, action, justification, status "
            "FROM files ORDER BY importance_score ASC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        # Default: show all files with recommendations, sorted lowest-score first
        # (most likely archival candidates at the top)
        rows = conn.execute(
            """
            SELECT path, size, atime, mtime, importance_score, action, justification, status
            FROM files
            WHERE action IS NOT NULL
              AND status != 'rejected'
            ORDER BY importance_score ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    conn.close()

    if not rows:
        console.print("[yellow]No recommendations yet. Run [cyan]intent-store scan <dir>[/cyan] first.[/yellow]")
        return

    import time as _time

    table = Table(
        title="[bold]Intent-Store Recommendations[/bold]",
        box=box.ROUNDED,
        show_lines=True,
        highlight=True,
    )
    table.add_column("File", style="cyan", max_width=36, no_wrap=False)
    table.add_column("Size", justify="right", style="magenta")
    table.add_column("Last Access", justify="center")
    table.add_column("Score", justify="right")
    table.add_column("Action", justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Justification", max_width=65, no_wrap=False)

    for row in rows:
        filename   = Path(row["path"]).name
        size_hr    = _fmt_size(row["size"])
        days_ago   = (_time.time() - row["atime"]) / 86400
        access_str = f"{days_ago:.0f}d ago"
        score      = f"{row['importance_score']:.3f}"
        action     = row["action"] or "—"
        status     = row["status"] or "pending"
        just       = row["justification"] or ""

        color, icon = ACTION_STYLES.get(action, ("white", "❓"))
        action_cell = f"[{color}]{icon} {action}[/{color}]"

        status_cell = {
            "accepted": "[green]accepted[/green]",
            "rejected": "[red]rejected[/red]",
            "pending":  "[yellow]pending[/yellow]",
        }.get(status, status)

        table.add_row(filename, size_hr, access_str, score, action_cell, status_cell, just)

    console.print(table)

    # Count files not shown (above threshold, no recommendation)
    conn2 = get_connection(db_path=db)
    total = conn2.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    conn2.close()
    hidden = total - len(rows)
    hidden_note = (
        f"  [dim]{hidden} additional file(s) scored above the archival threshold "
        f"and need no action. Use [cyan]--all[/cyan] to view them.[/dim]"
        if hidden > 0 else ""
    )
    console.print(
        f"\n[dim]Showing {len(rows)} recommendation(s). "
        "Use [cyan]accept <path>[/cyan] or [cyan]reject <path>[/cyan] to record decisions.[/dim]"
        + (f"\n{hidden_note}" if hidden_note else "")
    )


# ── accept ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("path", type=click.Path())
@click.pass_context
def accept(ctx: click.Context, path: str) -> None:
    """Accept the recommendation for PATH (boosts importance score)."""
    db = ctx.obj["db"]
    conn = get_connection(db_path=db)

    resolved = str(Path(path).resolve())
    row = conn.execute("SELECT importance_score, action FROM files WHERE path = ?", (resolved,)).fetchone()
    if row is None:
        console.print(f"[red]Path not found in database:[/red] {resolved}")
        conn.close()
        sys.exit(1)

    new_score = min(row["importance_score"] + ACCEPT_BOOST, 1.0)
    conn.execute(
        "UPDATE files SET status = 'accepted', importance_score = ? WHERE path = ?",
        (new_score, resolved),
    )
    conn.commit()
    conn.close()
    console.print(
        f"[green]✔ Accepted[/green] recommendation for [cyan]{Path(resolved).name}[/cyan] "
        f"→ action=[bold]{row['action']}[/bold], score boosted to {new_score:.3f}."
    )


# ── reject ────────────────────────────────────────────────────────────────────

@cli.command()
@click.argument("path", type=click.Path())
@click.pass_context
def reject(ctx: click.Context, path: str) -> None:
    """Reject the recommendation for PATH (penalises importance score)."""
    db = ctx.obj["db"]
    conn = get_connection(db_path=db)

    resolved = str(Path(path).resolve())
    row = conn.execute("SELECT importance_score, action FROM files WHERE path = ?", (resolved,)).fetchone()
    if row is None:
        console.print(f"[red]Path not found in database:[/red] {resolved}")
        conn.close()
        sys.exit(1)

    new_score = max(row["importance_score"] - REJECT_PENALTY, 0.0)
    conn.execute(
        "UPDATE files SET status = 'rejected', importance_score = ?, "
        "action = NULL, justification = NULL WHERE path = ?",
        (new_score, resolved),
    )
    conn.commit()
    conn.close()
    console.print(
        f"[red]✖ Rejected[/red] recommendation for [cyan]{Path(resolved).name}[/cyan]. "
        f"Score adjusted to {new_score:.3f}. "
        "Recommendation cleared."
    )


# ── helpers ───────────────────────────────────────────────────────────────────

def _fmt_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli(obj={})
