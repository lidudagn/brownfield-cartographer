"""
Performance and integration tests for Cartographer phase 1.

Includes synthetic 1000-file corpus generation and time limits (MF-5, F-10).
"""

import subprocess
import time
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.orchestrator import run_analysis


@patch("src.agents.semanticist.completion")
def test_performance_jaffle_shop(mock_completion):
    """Verify jaffle-shop finishes in < 5 seconds."""
    # Assuming tests are run from the project root and jaffle-shop is adjacent
    repo_path = Path(__file__).parent.parent.parent / "jaffle-shop"
    
    if not repo_path.exists():
        pytest.skip(f"jaffle-shop not found at {repo_path}")
        
    start_time = time.time()
    result = run_analysis(
        repo_path=str(repo_path),
        output_dir="/tmp/test_cart_jaffle",
        workers=4,
    )
    duration = time.time() - start_time
    
    assert result is not None, "Analysis failed"
    assert duration < 5.0, f"jaffle-shop analysis took {duration:.1f}s, expected < 5s"
    assert len(result.modules) > 0, "No modules found"


@pytest.mark.timeout(65)
@patch("src.agents.semanticist.completion")
def test_performance_1000_files(mock_completion):
    """Generate 1000 synthetic files and measure parallel processing time."""
    with TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        # 1. Generate 1000 Python files with varying complexity
        for i in range(1000):
            content = f"import os\n\ndef func_{i}(x):\n"
            for j in range(50):  # 50 lines of code each
                content += f"    if x > {j}:\n        return {j}\n"
            content += "    return 0\n"
            (tmp_path / f"mod_{i}.py").write_text(content)
            
        # 2. Init git repo so git velocity doesn't completely fail
        subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmpdir)
        subprocess.run(["git", "config", "user.name", "test"], cwd=tmpdir)
        subprocess.run(["git", "add", "."], cwd=tmpdir, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmpdir, check=True, capture_output=True)
        
        # 3. Time the orchestrator
        start_time = time.time()
        result = run_analysis(
            repo_path=tmpdir,
            output_dir=f"{tmpdir}/.cartography",
            workers=4,
        )
        duration = time.time() - start_time
        
        assert result is not None, "Analysis failed"
        assert len(result.modules) == 1000, f"Expected 1000 modules, got {len(result.modules)}"
        assert duration < 60.0, f"Took {duration:.1f}s, expected < 60.0s for 1000 files"
