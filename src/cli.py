"""
Command-line Interface for The Brownfield Cartographer.
"""

import logging
from pathlib import Path

import click

from src.orchestrator import run_analysis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@click.group()
def main() -> None:
    """The Brownfield Cartographer — Codebase Intelligence System"""
    pass


@main.command()
@click.option(
    "--repo-path",
    required=True,
    help="Path to repository to analyze",
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
def analyze(
    repo_path: str,
    output_dir: str,
    dialect: str,
    workers: int,
    days: int,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Run full Surveyor analysis on a production codebase."""
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        
    logger.info(f"Starting Surveyor analysis on {repo_path}")
    
    result = run_analysis(
        repo_path=repr(Path(repo_path).absolute()).strip("'"),
        output_dir=repr(Path(output_dir).absolute()).strip("'"),
        dialect=dialect,
        workers=workers,
        days=days,
        dry_run=dry_run,
        verbose=verbose,
    )
    
    if result:
        logger.info("Analysis successfully completed.")
    else:
        logger.warning("Analysis finished with no graph output.")


if __name__ == "__main__":
    main()
