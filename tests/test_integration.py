"""
Integration tests for the full Surveyor Agent pipeline on a valid dataset.
"""

import time
import pytest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.orchestrator import run_analysis
from src.graph.knowledge_graph import KnowledgeGraphWrapped

def test_integration_pipeline_outputs():
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
        
        # Run pipeline
        out_dir = tmp / ".cartography"
        cg = run_analysis(
            repo_path=str(tmp),
            output_dir=str(out_dir),
            workers=2,
        )
        
        # Verify outputs exist
        assert (out_dir / "module_graph.json").exists()
        assert (out_dir / "module_graph.png").exists()
        
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
