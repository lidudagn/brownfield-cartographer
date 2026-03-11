"""
Tests for TreeSitterAnalyzer parsing, complexity, comment ratio, and dynamic imports.
"""

from src.analyzers.tree_sitter_analyzer import TreeSitterAnalyzer


def test_python_parsing_and_complexity():
    """Verify complexity is M = decision_points + 1 and functions are extracted."""
    analyzer = TreeSitterAnalyzer()
    source = """
import os
from .local import relative_module

def main(val):
    if val > 5:
        return True
    elif val < 0:
        for i in range(5):
            pass
    return False

class MyClass:
    pass
"""
    # Setup test file
    analyzer._file_cache["test.py"] = source
    node = analyzer._analyze_python("test.py", source, ".")
    
    assert node.is_complete_parse
    assert node.lines_of_code == 14
    assert "os" in node.imports
    assert "main(val)" in node.public_functions
    assert "MyClass" in node.classes
    # Complexity: if + elif + for = 3 decision points -> M = 4
    assert node.complexity_score == 4


def test_python_comment_ratio():
    """Verify comment ratio calculation is line-based."""
    analyzer = TreeSitterAnalyzer()
    source = """
# This is a comment
# Another comment
def simple():
    pass # Inline comment
"""
    analyzer._file_cache["test_comments.py"] = source
    node = analyzer._analyze_python("test_comments.py", source, ".")
    
    assert node.is_complete_parse
    assert node.lines_of_code == 5
    # Lines 2, 3, 5 contain comments -> 3 / 5 = 0.6
    assert abs(node.comment_ratio - 0.6) < 0.01


def test_python_dynamic_imports():
    """Verify dynamic imports flag UnresolvedReferences."""
    analyzer = TreeSitterAnalyzer()
    source = """
def load_plugin(name):
    mod = __import__(name)
    import importlib
    mod2 = importlib.import_module(name)
"""
    analyzer._file_cache["test_dynamic.py"] = source
    imports, unresolved = analyzer._extract_python_imports(
        analyzer.router.get_parser("python").parse(source.encode("utf-8")).root_node,
        source, "test_dynamic.py", "."
    )
    
    assert "importlib" in imports
    assert len(unresolved) == 2
    assert unresolved[0].ref_type == "dynamic_import"

def test_python_data_flows():
    """Verify PySpark and Pandas method chains extract read/write datasets."""
    analyzer = TreeSitterAnalyzer()
    source = """
import pandas as pd
df = pd.read_csv("data/input.csv")
df.to_parquet("data/output.parquet")

spark_df = spark.read.format("json").load("s3://bucket/raw_events")
spark_df.write.mode("overwrite").saveAsTable("analytics.events")
"""
    analyzer._file_cache["test_flows.py"] = source
    node = analyzer._analyze_python("test_flows.py", source, ".")
    
    assert "data/input.csv" in node.datasets_read
    assert "s3://bucket/raw_events" in node.datasets_read
    assert "data/output.parquet" in node.datasets_written
    assert "analytics.events" in node.datasets_written
