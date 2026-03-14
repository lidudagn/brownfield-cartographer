"""
Integration tests for the full Surveyor Agent pipeline on a valid dataset.
"""

import time
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from tempfile import TemporaryDirectory

from src.orchestrator import run_analysis
from src.graph.knowledge_graph import KnowledgeGraphWrapped


@patch("src.agents.semanticist.completion")
def test_integration_pipeline_outputs(mock_completion):
    """Test full pipeline generates correct files and graph structure."""
    with TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # Setup fake codebase
        (tmp / "models" / "marts").mkdir(parents=True)
        (tmp / "seeds").mkdir()

        # 1. dbt_project.yml
        (tmp / "dbt_project.yml").write_text("""
name: test_proj
version: '1.0'
seed-paths: ["seeds"]
        """)

        # 2. Seed file
        (tmp / "seeds" / "raw_customers.csv").write_text("id,name\\n1,alice")

        # 3. Model
        (tmp / "models" / "marts" / "customers.sql").write_text("""
        select * from {{ ref('raw_customers') }}
        """)

        # Configure mock completion to return a serializable object
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Test purpose"))]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
        mock_completion.return_value = mock_response

        # Configure mock completion to return a serializable object
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="Test purpose"))]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=10)
        mock_completion.return_value = mock_response

        # Run pipeline
        out_dir = tmp / ".cartography"
        cg = run_analysis(
            repo_path=str(tmp),
            output_dir=str(out_dir),
            workers=2,
        )

        # Verify core outputs exist
        assert (out_dir / "module_graph.json").exists()
        import importlib.util
        if importlib.util.find_spec("matplotlib"):
            assert (out_dir / "module_graph.png").exists()

        # Verify Archivist artifacts
        assert (out_dir / "CODEBASE.md").exists(), "Archivist should generate CODEBASE.md"
        assert (out_dir / "onboarding_brief.md").exists(), "Archivist should generate onboarding_brief.md"
        assert (out_dir / "cartography_trace.jsonl").exists(), "Archivist should generate trace log"

        # Verify CODEBASE.md has required sections
        codebase_content = (out_dir / "CODEBASE.md").read_text()
        assert "Architecture Overview" in codebase_content
        assert "Critical Path" in codebase_content
        assert "Module Purpose Index" in codebase_content

        # Verify graph contents
        assert cg is not None
        assert len(cg.modules) == 3

        # Check seed
        seeds = [m for m in cg.modules if m.language == "csv"]
        assert len(seeds) == 1
        assert seeds[0].is_entry_point
        assert seeds[0].entry_point_type == "seed"

        # Check mart (dbt path inference)
        marts = [m for m in cg.modules if m.language == "jinja_sql"]
        assert len(marts) == 1
        assert marts[0].is_entry_point
        assert marts[0].entry_point_type == "mart"

        # Test deserialization
        kg = KnowledgeGraphWrapped.load(out_dir / "module_graph.json")
        assert len(kg.codebase.modules) == 3
