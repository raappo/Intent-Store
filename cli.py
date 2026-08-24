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

import time
import click
from pathlib import Path
from rich.console import Console
from rich.table import Table

from scanner import get_connection, DB_PATH, scan_directory
from profiler import embed_all
from scorer import score_all
from reasoner import reason_all

console = Console()
REJECT_PENALTY = 0.20
ACCEPT_BOOST = 0.15

@click.group()
@click.option("--db", "db_path", default=DB_PATH, help="Path to SQLite database.")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.pass_context
def cli(ctx: click.Context, db_path: str, verbose: bool) -> None:
    ctx.ensure_object(dict)
    ctx.obj["db"] = db_path

    import logging
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


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


@cli.command()
@click.option("--all", "show_all", is_flag=True, help="Show all files, not just recommendations.")
@click.option("--limit", default=20, help="Max rows to show.")
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
        rows = conn.execute(
            """
            SELECT path, size, atime, mtime, importance_score, action, justification, status
            FROM files
            WHERE action IS NOT NULL
            ORDER BY importance_score ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    if not rows:
        console.print("[yellow]No recommendations yet. Run [cyan]intent-store scan <dir>[/cyan] first.[/yellow]")
        conn.close()
        return

    table = Table(title="Intent-Store Recommendations", show_lines=True)
    table.add_column("File", style="cyan", no_wrap=True)
    table.add_column("Size", justify="right")
    table.add_column("Last Access", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Action", justify="center")
    table.add_column("Status", justify="center")
    table.add_column("Justification", max_width=65, no_wrap=False)

    def _fmt_size(size_bytes: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} PB"

    ACTION_STYLES = {
        "archive": ("red", "📦"),
        "keep": ("green", "✅"),
        "compress": ("yellow", "🗜️"),
    }

    for row in rows:
        filename   = Path(row["path"]).name
        size_hr    = _fmt_size(row["size"])
        days_ago   = max(0.0, (time.time() - row["atime"]) / 86400.0)
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


@cli.command()
@click.argument("path", type=click.Path())
@click.pass_context
def debug(ctx: click.Context, path: str) -> None:
    """Print raw embedding length and similarity score for PATH."""
    db = ctx.obj["db"]
    conn = get_connection(db_path=db)
    
    resolved = str(Path(path).resolve())
    row = conn.execute("SELECT embedding FROM files WHERE path = ?", (resolved,)).fetchone()
    if row is None:
        print(f"Path not found in database: {resolved}")
        conn.close()
        return

    from profiler import deserialize
    from scorer import _get_importance_centroid, _cosine_similarity
    
    vec = deserialize(row["embedding"])
    centroid = _get_importance_centroid()
    sim_score = _cosine_similarity(vec, centroid) if vec is not None else 0.0
    
    print(f"File path: {resolved}")
    if vec is not None:
        print(f"embedding length: {len(vec)}")
    else:
        print("embedding length: None")
    print(f"raw similarity score: {sim_score}")
    
    conn.close()


@cli.command()
@click.argument("path", type=click.Path())
@click.pass_context
def accept(ctx: click.Context, path: str) -> None:
    """Accept the recommendation for PATH (boosts importance score)."""
    db = ctx.obj["db"]
    conn = get_connection(db_path=db)

    resolved = str(Path(path).resolve())
    row = conn.execute("SELECT importance_score, action, justification FROM files WHERE path = ?", (resolved,)).fetchone()
    if row is None:
        console.print(f"[red]Path not found in database:[/red] {resolved}")
        conn.close()
        import sys; sys.exit(1)

    new_score = min(row["importance_score"] + ACCEPT_BOOST, 1.0)
    old_just = row["justification"] or ""
    new_just = f"{old_just} (Adjusted based on prior user feedback: Accepted)"
    
    conn.execute(
        "UPDATE files SET status = 'accepted', importance_score = ?, justification = ? WHERE path = ?",
        (new_score, new_just, resolved),
    )
    conn.commit()
    conn.close()
    console.print(
        f"[green]✔ Accepted[/green] recommendation for [cyan]{Path(resolved).name}[/cyan] "
        f"→ action=[bold]{row['action']}[/bold], score boosted to {new_score:.3f}."
    )


@cli.command()
@click.argument("path", type=click.Path())
@click.pass_context
def reject(ctx: click.Context, path: str) -> None:
    """Reject the recommendation for PATH (penalises importance score)."""
    db = ctx.obj["db"]
    conn = get_connection(db_path=db)

    resolved = str(Path(path).resolve())
    row = conn.execute("SELECT importance_score, action, justification FROM files WHERE path = ?", (resolved,)).fetchone()
    if row is None:
        console.print(f"[red]Path not found in database:[/red] {resolved}")
        conn.close()
        import sys; sys.exit(1)

    new_score = max(row["importance_score"] - REJECT_PENALTY, 0.0)
    old_just = row["justification"] or ""
    new_just = f"{old_just} (Adjusted based on prior user feedback: Rejected)"
    
    conn.execute(
        "UPDATE files SET status = 'rejected', importance_score = ?, justification = ? WHERE path = ?",
        (new_score, new_just, resolved),
    )
    conn.commit()
    conn.close()
    console.print(
        f"[red]✖ Rejected[/red] recommendation for [cyan]{Path(resolved).name}[/cyan]. "
        f"Score adjusted to {new_score:.3f}. "
        "Recommendation cleared."
    )


@cli.command()
@click.pass_context
def export(ctx: click.Context) -> None:
    """Export the recommendations table to web/data.json."""
    import json
    import os
    
    db = ctx.obj["db"]
    conn = get_connection(db_path=db)

    rows = conn.execute(
        "SELECT path, size, atime, importance_score, action, justification, status "
        "FROM files ORDER BY importance_score ASC"
    ).fetchall()

    out = []
    for row in rows:
        filename = Path(row["path"]).name
        size = row["size"]
        days_ago = max(0.0, (time.time() - row["atime"]) / 86400.0)
        score = row["importance_score"]
        action = row["action"] or "—"
        status = row["status"] or "pending"
        just_raw = row["justification"] or ""
        
        source = "UNKNOWN"
        if just_raw.startswith("[LLM]"):
            source = "LLM"
            just_raw = just_raw[5:].strip()
        elif just_raw.startswith("[RULE]"):
            source = "RULE"
            just_raw = just_raw[6:].strip()

        out.append({
            "file": filename,
            "size": size,
            "last_access": f"{days_ago:.0f} days ago",
            "score": score,
            "action": action,
            "status": status,
            "justification": just_raw,
            "source": source
        })

    os.makedirs("web", exist_ok=True)
    with open("web/data.json", "w") as f:
        json.dump(out, f, indent=2)
    conn.close()

    console.print(f"[green]✔[/green] Exported {len(out)} files to [bold]web/data.json[/bold]")


if __name__ == "__main__":
    cli(obj={})
