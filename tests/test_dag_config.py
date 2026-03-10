"""
Tests for DAG configuration parsers, entry points, and schema drift.
"""

from tempfile import NamedTemporaryFile
from pathlib import Path

from src.analyzers.dag_config_parser import (
    parse_dbt_project,
    parse_sources,
    detect_entry_points,
    detect_schema_drift,
)
from src.models.schemas import ModuleNode, DbtProjectConfig

def test_parse_sources_yaml():
    yaml_content = """
version: 2
sources:
  - name: ecom
    tables:
      - name: raw_orders
        loaded_at_field: _etl_loaded_at
        meta:
          owner: data@example.com
        columns:
          - name: id
            data_type: integer
          - name: status
            data_type: varchar
    """
    with NamedTemporaryFile(mode="w", suffix=".yml") as f:
        f.write(yaml_content)
        f.flush()
        
        datasets = parse_sources(f.name)
        
        assert len(datasets) == 1
        ds = datasets[0]
        assert ds.name == "ecom.raw_orders"
        assert ds.freshness_sla == "_etl_loaded_at"
        assert ds.owner == "data@example.com"
        assert ds.schema_snapshot["id"] == "integer"
        assert ds.schema_snapshot["status"] == "varchar"


def test_detect_entry_points():
    modules = [
        ModuleNode(path="models/marts/orders.sql", language="jinja_sql"),
        ModuleNode(path="seeds/raw_data.csv", language="csv"),
        ModuleNode(path="src/utils.py", language="python"),
    ]
    
    config = DbtProjectConfig(seed_paths=["seeds"])
    
    # Needs repo root, but our test cases here use strings
    detect_entry_points(modules, config, ".")
    
    assert modules[0].is_entry_point
    assert modules[0].entry_point_type == "mart"
    
    assert modules[1].is_entry_point
    assert modules[1].entry_point_type == "seed"
    
    assert not modules[2].is_entry_point


def test_schema_drift():
    sql_cols = ["id", "status", "created_at"]
    yaml_cols = ["id", "status", "updated_at"]
    
    drifts = detect_schema_drift(sql_cols, yaml_cols, "model.sql", "schema.yml")
    assert len(drifts) == 2
    
    in_sql = next(d for d in drifts if d["issue"] == "in_sql_not_yaml")
    assert in_sql["column"] == "created_at"
    
    in_yaml = next(d for d in drifts if d["issue"] == "in_yaml_not_sql")
    assert in_yaml["column"] == "updated_at"
