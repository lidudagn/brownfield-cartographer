"""
Command-line Interface for The Brownfield Cartographer.

Supports both local repository paths and GitHub URLs.
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import click

from src.orchestrator import run_analysis, run_incremental

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# ── GitHub URL Cloning ──────────────────────────────────────────────────────


_GITHUB_URL_PATTERN = re.compile(
    r"^(https?://|git@)(github\.com|gitlab\.com|bitbucket\.org)[/:][\w.\-]+/[\w.\-]+(?:/\w+)*(\.git)?/?$"
)


def _is_git_url(path: str) -> bool:
    """Detect whether *path* is a remote Git URL rather than a local path."""
    return bool(_GITHUB_URL_PATTERN.match(path))


def _extract_repo_name(url: str) -> str:
    """Extract a human-readable repo name from a Git URL."""
    base = url.rstrip("/").rsplit("/", 1)[-1]
    return base.removesuffix(".git")


def _clone_repo(url: str, target_dir: str, depth: int = 1) -> str:
    """Clone a remote repository into *target_dir* and return the clone path."""
    repo_name = _extract_repo_name(url)
    clone_path = os.path.join(target_dir, repo_name)
    logger.info(f"Cloning {url} → {clone_path} (depth={depth})")
    subprocess.run(
        ["git", "clone", "--depth", str(depth), url, clone_path],
        check=True,
        capture_output=True,
        text=True,
    )
    logger.info(f"Clone complete: {clone_path}")
    return clone_path


# ── Artifact Summary ────────────────────────────────────────────────────────

# Ordered list of artifacts the pipeline may produce.
_EXPECTED_ARTIFACTS = [
    ("module_graph.json", "Full codebase knowledge graph (all nodes + edges)"),
    ("lineage_graph.json", "Data lineage DAG (transformations + datasets)"),
    ("CODEBASE.md", "Living context file for AI agent injection"),
    ("modules.json", "Module & function inventory"),
    ("datasets.json", "Discovered data sources and sinks"),
    ("transformations.json", "SQL/Python transformation nodes"),
    ("edges.json", "All edge types (imports, calls, produces, consumes, configures)"),
    ("analysis_report.json", "Architecture insights and risk analysis"),
    ("onboarding_brief.md", "FDE Day-One Brief (5 questions answered)"),
    ("cartography_trace.jsonl", "Audit trail of every analysis action"),
    ("module_graph.png", "Visual graph (PageRank × Git Velocity)"),
    ("semantic_index/", "Vector store of module purpose embeddings"),
]


def _print_artifact_summary(output_dir: str) -> None:
    """Print a clear manifest of every generated artifact."""
    out = Path(output_dir)
    click.echo("")
    click.echo("=" * 68)
    click.echo("  CARTOGRAPHY ARTIFACTS")
    click.echo("=" * 68)
    for filename, description in _EXPECTED_ARTIFACTS:
        filepath = out / filename
        if filepath.exists():
            size_kb = filepath.stat().st_size / 1024
            click.echo(f"  ✓ {filename:<30s} {size_kb:>7.1f} KB  {description}")
        else:
            click.echo(f"  ✗ {filename:<30s}          —  (not generated)")
    click.echo("=" * 68)
    click.echo(f"  Output directory: {out.resolve()}")
    click.echo("=" * 68)
    click.echo("")


# ── CLI Commands ────────────────────────────────────────────────────────────


@click.group()
def main() -> None:
    """The Brownfield Cartographer — Codebase Intelligence System"""
    pass


@main.command()
@click.option(
    "--repo-path",
    required=True,
    help="Local path OR GitHub URL (https://github.com/org/repo) to analyze",
)
@click.option(
    "--output-dir",
    default=".cartography",
    help="Output directory for reports",
)
@click.option(
    "--dialect",
    default="auto",
    help="SQL dialect (auto|postgres|bigquery|snowflake|duckdb)",
)
@click.option(
    "--workers",
    default=4,
    help="Parallel workers for file analysis",
)
@click.option(
    "--days",
    default=30,
    help="Git velocity lookback window in days",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Report what would be analyzed without executing",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Enable debug logging",
)
@click.option(
    "--incremental",
    is_flag=True,
    help="Only re-analyze files changed since last analysis (falls back to full)",
)
def analyze(
    repo_path: str,
    output_dir: str,
    dialect: str,
    workers: int,
    days: int,
    dry_run: bool,
    verbose: bool,
    incremental: bool,
) -> None:
    """Run full analysis on a production codebase (local path or GitHub URL)."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Resolve repo path (local or remote) ─────────────────────────────
    tmp_clone_dir = None
    resolved_path = repo_path

    if _is_git_url(repo_path):
        tmp_clone_dir = tempfile.mkdtemp(prefix="cartographer_clone_")
        try:
            resolved_path = _clone_repo(repo_path, tmp_clone_dir)
        except subprocess.CalledProcessError as exc:
            logger.error(f"Failed to clone {repo_path}: {exc.stderr}")
            click.echo(f"Error: could not clone {repo_path}", err=True)
            if tmp_clone_dir:
                shutil.rmtree(tmp_clone_dir, ignore_errors=True)
            raise SystemExit(1)
    else:
        resolved_path = str(Path(repo_path).absolute())

    logger.info(f"Starting Cartographer analysis on {resolved_path}")

    try:
        if incremental:
            logger.info("Running incremental analysis (changed files only)...")
            result = run_incremental(
                repo_path=resolved_path,
                output_dir=str(Path(output_dir).absolute()),
                dialect=dialect,
                workers=workers,
                days=days,
                verbose=verbose,
            )
        else:
            result = run_analysis(
                repo_path=resolved_path,
                output_dir=str(Path(output_dir).absolute()),
                dialect=dialect,
                workers=workers,
                days=days,
                dry_run=dry_run,
                verbose=verbose,
            )

        if result:
            logger.info("Analysis successfully completed.")
            _print_artifact_summary(str(Path(output_dir).absolute()))
        else:
            logger.warning("Analysis finished with no graph output.")
    finally:
        # Clean up temporary clone directory
        if tmp_clone_dir and os.path.exists(tmp_clone_dir):
            logger.info(f"Cleaning up temporary clone at {tmp_clone_dir}")
            shutil.rmtree(tmp_clone_dir, ignore_errors=True)


@main.command()
@click.option(
    "--output-dir",
    default=".cartography",
    help="Directory containing analysis artifacts",
)
@click.option(
    "--verbose",
    is_flag=True,
    help="Enable debug logging",
)
def query(
    output_dir: str,
    verbose: bool,
) -> None:
    """Interactive Navigator agent for querying the codebase knowledge graph."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    out = Path(output_dir).absolute()
    graph_path = out / "module_graph.json"

    if not graph_path.exists():
        click.echo(
            f"Error: No analysis found at {out}. Run 'cartographer analyze' first.",
            err=True,
        )
        raise SystemExit(1)

    # Load the knowledge graph
    logger.info(f"Loading knowledge graph from {graph_path}")
    try:
        from src.graph.knowledge_graph import KnowledgeGraphWrapped
        wrapper = KnowledgeGraphWrapped.load(graph_path)
        codebase_graph = wrapper.codebase
    except Exception as e:
        click.echo(f"Error loading knowledge graph: {e}", err=True)
        raise SystemExit(1)

    # Build lineage graph
    from src.agents.hydrologist import Hydrologist
    hydro = Hydrologist()
    hydro.build_lineage_graph(codebase_graph)

    # Launch Navigator REPL
    from src.agents.navigator import NavigatorAgent
    nav = NavigatorAgent(codebase_graph, hydro, codebase_graph.repo_path)
    nav.run_repl()


@main.command()
def ui() -> None:
    """Launch the interactive Streamlit Web UI (optional frontend)."""
    app_path = Path(__file__).resolve().parent.parent / "app.py"
    if not app_path.exists():
        click.echo(f"Error: app.py not found at {app_path}", err=True)
        raise SystemExit(1)

    click.echo("🗺️  Launching Brownfield Cartographer Web UI...")
    click.echo(f"   App: {app_path}")
    click.echo("   Press Ctrl+C to stop.\n")
    try:
        subprocess.run(
            ["streamlit", "run", str(app_path), "--server.headless", "true"],
            check=True,
        )
    except KeyboardInterrupt:
        click.echo("\nUI stopped.")
    except FileNotFoundError:
        click.echo("Error: streamlit not installed. Run: uv add streamlit", err=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
