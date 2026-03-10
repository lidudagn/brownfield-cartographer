"""
SQL Lineage extraction using sqlglot.

Detects SQL dialects, pre-processes dbt-flavored SQL, and extracts column-level
lineage from SQL ASTs for deep data flow understanding.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import sqlglot
import sqlglot.expressions as exp
import yaml

from src.models.schemas import (
    ColumnLineage,
    Evidence,
    UnresolvedReference,
)
from src.analyzers.tree_sitter_analyzer import create_evidence_from_line

logger = logging.getLogger(__name__)


# =============================================================================
# Dialect Auto-Detection (M-4)
# =============================================================================


def detect_dialect(dbt_project_path: str) -> str:
    """Read dbt_project.yml profile to map to sqlglot dialect.
    
    Fallback: try parsing with each dialect until one succeeds.
    """
    profile_map = {
        "postgres": "postgres",
        "bigquery": "bigquery",
        "snowflake": "snowflake",
        "duckdb": "duckdb",
        "redshift": "redshift",
        "databricks": "databricks",
        "spark": "spark",
        "trino": "trino",
    }
    
    try:
        if Path(dbt_project_path).exists():
            cfg = yaml.safe_load(Path(dbt_project_path).read_text())
            profile = cfg.get("profile", "").lower()
            if profile in profile_map:
                logger.debug(f"Auto-detected dialect {profile_map[profile]} from {dbt_project_path}")
                return profile_map[profile]
    except Exception as e:
        logger.warning(f"Failed to read dbt_project.yml for dialect detection: {e}")

    # Default fallback
    return "postgres"


def test_dialect_parse(sql: str, dialects: List[str] = ["postgres", "bigquery", "snowflake", "duckdb"]) -> str:
    """Try parsing SQL with multiple dialects, return the first that works."""
    # Preprocess Jinja first so it's valid SQL
    clean_sql, _, _ = preprocess_dbt_sql(sql, "test.sql")
    
    for dialect in dialects:
        try:
            sqlglot.parse(clean_sql, read=dialect)
            return dialect
        except sqlglot.errors.ParseError:
            continue
            
    return "postgres" # Ultimate fallback


# =============================================================================
# Jinja Preprocessing
# =============================================================================


def preprocess_dbt_sql(
    raw_sql: str, filepath: str
) -> Tuple[str, List[Evidence], List[Evidence], List[UnresolvedReference]]:
    """
    1. Extract ref() → __dbt_ref__ model
    2. Extract source() → __dbt_source__ schema table
    3. Flag dynamic/macro refs
    4. Strip remaining Jinja
    
    Returns: (clean_sql, ref_evidence, source_evidence, unresolved_refs)
    """
    ref_evidences: List[Evidence] = []
    source_evidences: List[Evidence] = []
    unresolved: List[UnresolvedReference] = []
    
    lines = raw_sql.splitlines()

    # 1. Static refs
    # {{ ref('model') }}
    for i, line in enumerate(lines):
        ref_matches = re.finditer(r"\{\{\s*ref\(\s*'(\w+)'\s*\)\s*\}\}", line)
        for m in ref_matches:
            model = m.group(1)
            ref_evidences.append(create_evidence_from_line(
                filepath, i + 1, raw_sql, "regex"
            ))
            
        source_matches = re.finditer(r"\{\{\s*source\(\s*'(\w+)'\s*,\s*'(\w+)'\s*\)\s*\}\}", line)
        for m in source_matches:
            source_evidences.append(create_evidence_from_line(
                filepath, i + 1, raw_sql, "regex"
            ))
            
        # Dynamic / macro-wrapped refs (M-3/Dynamic)
        dyn_matches = re.finditer(r"\{\{\s*ref\(\s*(?!')[^)]+\)\s*\}\}", line)
        for m in dyn_matches:
            unresolved.append(
                UnresolvedReference(
                    ref_type="macro_ref",
                    raw_text=m.group(0),
                    source_file=filepath,
                    source_line=i + 1,
                    reason="Dynamic/macro-wrapped ref() — cannot resolve statically",
                )
            )

    # Replace tags with table names for sqlglot parsing
    clean = re.sub(
        r"\{\{\s*ref\(\s*'(\w+)'\s*\)\s*\}\}",
        r"__dbt_ref__\1",
        raw_sql,
    )
    clean = re.sub(
        r"\{\{\s*source\(\s*'(\w+)'\s*,\s*'(\w+)'\s*\)\s*\}\}",
        r"__dbt_source__\1__\2",
        clean,
    )
    
    # Strip remaining Jinja
    clean = re.sub(r"\{\{.*?\}\}", "NULL", clean)
    clean = re.sub(r"\{%.*?%\}", "", clean, flags=re.DOTALL)
    clean = re.sub(r"\{#.*?#\}", "", clean, flags=re.DOTALL)
    
    return clean, ref_evidences, source_evidences, unresolved


# =============================================================================
# Column Lineage Extraction (MF-1)
# =============================================================================


def _categorize_transform(expr: exp.Expression) -> str:
    """Infer transformation type from sqlglot expression."""
    if isinstance(expr, exp.Column):
        return "passthrough"
    # An alias wrapping a column is a rename
    if isinstance(expr, exp.Alias) and isinstance(expr.this, exp.Column):
        return "rename"
    if list(expr.find_all(exp.AggFunc)):
        return "aggregate"
    if list(expr.find_all(exp.Window)):
        return "window"
    if list(expr.find_all(exp.Case)):
        return "case"
    if list(expr.find_all(exp.Cast)):
        return "cast"
    return "compute"


def extract_column_lineage(sql_text: str, source_file: str, dialect: str) -> List[ColumnLineage]:
    """Walk sqlglot AST to trace column provenance."""
    try:
        parsed = sqlglot.parse(sql_text, read=dialect)
    except sqlglot.errors.ParseError as e:
        logger.warning(f"sqlglot parse error in {source_file}: {e}")
        return []

    lineage = []
    
    lines = sql_text.splitlines()
    for ast in parsed:
        if not ast:
            continue
            
        for select in ast.find_all(exp.Select):
            for expr in select.expressions:
                # 1. Identify the target output column name
                if isinstance(expr, exp.Alias):
                    target_name = expr.alias
                    source_expr = expr.this
                elif isinstance(expr, exp.Column):
                    target_name = expr.name
                    source_expr = expr
                elif isinstance(expr, exp.Star):
                    target_name = "*"
                    source_expr = expr
                else:
                    # Some other expression without an alias, fallback to SQL string
                    target_name = str(expr)
                    source_expr = expr
                
                # Check for duplicate target in this lineage to prevent explosion
                if any(l.target_column == target_name for l in lineage):
                    continue

                # 2. Extract all source columns referenced in this expression
                source_cols = []
                for col in source_expr.find_all(exp.Column):
                    qual = f"{col.table}.{col.name}" if col.table else col.name
                    if qual not in source_cols:
                        source_cols.append(qual)
                
                # 3. Categorize the transformation
                transform = _categorize_transform(source_expr)
                if target_name == "*":
                    transform = "wildcard_passthrough"
                
                # Find line number (approximate by string match)
                start_line = 0
                for i, line in enumerate(lines):
                    if target_name != "*" and target_name in line:
                        start_line = i + 1
                        break
                    elif source_cols and source_cols[0] in line:
                        start_line = i + 1
                        break
                    elif target_name == "*" and "*" in line:
                        start_line = i + 1
                        break
                
                line_range = (start_line, start_line) if start_line > 0 else (1, len(lines))
                
                lineage.append(ColumnLineage(
                    target_column=target_name,
                    source_columns=source_cols,
                    transformation=transform,
                    expression=source_expr.sql(dialect=dialect) if source_cols else None,
                    source_file=source_file,
                    line_range=line_range
                ))
                
    return lineage


# =============================================================================
# Full SQL Analysis
# =============================================================================


def extract_sql_dependencies(
    raw_sql: str, filepath: str, dialect: str
) -> Tuple[List[str], List[ColumnLineage], List[Evidence], List[UnresolvedReference]]:
    """
    Extract table dependencies and column lineage from SQL.
    
    Returns: 
        dependencies (list of dbt refs/sources or SQL tables)
        column_lineages (List[ColumnLineage])
        evidences (List[Evidence] for refs)
        unresolved (List[UnresolvedReference] for macros)
    """
    clean_sql, ref_evidences, source_evidences, unresolved = preprocess_dbt_sql(raw_sql, filepath)
    
    lineage = extract_column_lineage(clean_sql, filepath, dialect)
    
    # Collect all dependencies
    deps = []
    for ev in ref_evidences:
        # Extract model from snippet: {{ ref('model') }}
        m = re.search(r"ref\(\s*'(\w+)'\s*\)", ev.snippet)
        if m:
            deps.append(m.group(1))
            
    for ev in source_evidences:
        m = re.search(r"source\(\s*'(\w+)'\s*,\s*'(\w+)'\s*\)", ev.snippet)
        if m:
            deps.append(f"source:{m.group(1)}.{m.group(2)}")
            
    # For non-dbt SQL codebases, we'd also walk sqlglot for exp.Table nodes
    # But for dbt, refs and sources are sufficient and more accurate.
    
    return deps, lineage, ref_evidences + source_evidences, unresolved
