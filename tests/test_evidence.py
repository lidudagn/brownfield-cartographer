"""
Tests for Evidence creation and verification.
"""

from tempfile import NamedTemporaryFile
from src.models.schemas import Evidence
from src.analyzers.tree_sitter_analyzer import create_evidence_from_line

def test_evidence_verify_success():
    """Verify that Evidence matches the file content."""
    content = """line 1
line 2
line 3
line 4"""
    
    with NamedTemporaryFile(mode="w", suffix=".txt") as f:
        f.write(content)
        f.flush()
        
        # Correct evidence
        ev = Evidence(
            file_path=f.name,
            line_start=2,
            line_end=2,
            snippet="line 2",
            analysis_method="regex"
        )
        assert ev.verify("/") is True


def test_evidence_verify_fail():
    """Verify that Evidence rejects mismatches."""
    content = """line 1
line 2
line 3"""
    
    with NamedTemporaryFile(mode="w", suffix=".txt") as f:
        f.write(content)
        f.flush()
        
        # Wrong snippet
        ev = Evidence(
            file_path=f.name,
            line_start=2,
            line_end=2,
            snippet="line 4",
            analysis_method="regex"
        )
        assert ev.verify("/") is False
        
        # Out of bounds
        ev_oob = Evidence(
            file_path=f.name,
            line_start=5,
            line_end=5,
            snippet="line 5",
            analysis_method="regex"
        )
        assert ev_oob.verify("/") is False


def test_create_evidence_from_line():
    source = "A\nB\nC\n"
    ev = create_evidence_from_line("test.txt", 2, source, "regex")
    assert ev.line_start == 2
    assert ev.snippet == "B"
