"""
Tests for Pydantic schema validation, error hierarchy, and YAML rejection.
"""

import pytest
from pydantic import ValidationError

from src.models.schemas import (
    AnalysisError,
    DeadCodeCandidate,
    ModuleNode,
    DbtProjectConfig,
)


def test_module_node_validation():
    """Test valid and invalid ModuleNode instantiation."""
    # Valid
    node = ModuleNode(
        path="src/main.py",
        language="python",
        complexity_score=5,
        change_velocity_30d=0.8,
        is_entry_point=True,
        entry_point_type="cli",
    )
    assert node.path == "src/main.py"
    assert node.language == "python"

    # Invalid language
    with pytest.raises(ValidationError) as exc:
        ModuleNode(path="test.java", language="java")
    assert "Input should be" in str(exc.value)

    # Forbid extra attributes
    with pytest.raises(ValidationError):
        ModuleNode(path="test.py", language="python", extra_field="bad")


def test_analysis_error_hierarchy():
    """Test AnalysisError types and recovery properties."""
    err = AnalysisError(
        error_type="parse_error",
        file_path="bad.py",
        message="SyntaxError: invalid syntax",
        recoverable=True,
        fallback_used="minimal_placeholder",
    )
    assert err.error_type == "parse_error"
    assert err.fallback_used == "minimal_placeholder"

    # Invalid error type
    with pytest.raises(ValidationError):
        AnalysisError(
            error_type="warning",
            file_path="bad.py",
            message="Watch out",
            recoverable=True,
            fallback_used="skipped",
        )


def test_dead_code_candidate_confidence():
    """Test confidence bounds for DeadCodeCandidate."""
    # Valid confidence
    cand = DeadCodeCandidate(
        module_path="old.py",
        in_degree=0,
        is_entry_point=False,
        explanation="No imports.",
        confidence=0.7,
        factors={"no_imports": True, "stale_90d": True},
    )
    assert cand.confidence == 0.7

    # Invalid confidence (must be 0.0 - 1.0)
    with pytest.raises(ValidationError):
        DeadCodeCandidate(
            module_path="old.py",
            in_degree=0,
            is_entry_point=False,
            explanation="Very dead.",
            confidence=1.5,
        )
    with pytest.raises(ValidationError):
        DeadCodeCandidate(
            module_path="old.py",
            in_degree=0,
            is_entry_point=False,
            explanation="Not dead.",
            confidence=-0.1,
        )


def test_yaml_rejection():
    """Test that poorly formed YAML config dictionaries are rejected."""
    # DbtProjectConfig requires 'name' and 'version'
    with pytest.raises(ValidationError):
        DbtProjectConfig(name=123, version=["1"]) # Invalid types
