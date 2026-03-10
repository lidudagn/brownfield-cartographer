"""
Tests for graceful degradation during parse errors and partial extraction.
"""

from src.analyzers.tree_sitter_analyzer import TreeSitterAnalyzer
from src.analyzers.dag_config_parser import parse_model_yaml

def test_python_parse_error():
    """Verify syntactic errors yield gracefully degraded ModuleNodes."""
    analyzer = TreeSitterAnalyzer()
    
    # Missing colon and indentation errors
    bad_python = """
def main()
    print("hello"
    """
    
    analyzer._file_cache["bad.py"] = bad_python
    node = analyzer._analyze_python("bad.py", bad_python, ".")
    
    # We still get a node back
    assert node is not None
    assert node.path == "bad.py"
    # But it shouldn't be completely parsed
    assert len(node.parse_errors) > 0
    err = node.parse_errors[0]
    assert err.error_type == "partial_parse"


def test_yaml_parse_error():
    """Verify bad YAML doesn't crash the pipeline."""
    analyzer = TreeSitterAnalyzer()
    
    bad_yaml = """
models:
  - name: my_model
   description: "Bad indent"
    """
    
    node = analyzer._analyze_yaml("bad.yml", bad_yaml, ".")
    assert not node.is_complete_parse
    assert len(node.parse_errors) == 1
    assert node.parse_errors[0].error_type == "parse_error"


def test_dbt_yaml_pydantic_validation_error():
    """Verify bad schema in dbt yaml gracefully defaults."""
    from tempfile import NamedTemporaryFile
    bad_yaml = """
version: not_an_int
sources: "string_instead_of_list"
    """
    with NamedTemporaryFile(mode="w", suffix=".yml") as f:
        f.write(bad_yaml)
        f.flush()
        
        # It should catch the ValidationError and return empty
        config = parse_model_yaml(f.name)
        assert len(config.models) == 0
