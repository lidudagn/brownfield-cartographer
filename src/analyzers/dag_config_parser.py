"""
YAML Configuration Parser for dbt and Airflow DAGs.

Parses dbt schema.yml, sources.yml, and dbt_project.yml into Pydantic models.
Detects entry points based on materializations, python file patterns, and config.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple

import yaml
from pydantic import ValidationError

from src.models.schemas import (
    DatasetNode,
    DbtModelConfig,
    DbtProjectConfig,
    DbtSourceConfig,
    ModuleNode,
)

logger = logging.getLogger(__name__)


# =============================================================================
# YAML Parsers (M-5)
# =============================================================================


def parse_dbt_project(yaml_path: str) -> DbtProjectConfig:
    """Parse dbt_project.yml with Pydantic validation."""
    try:
        content = Path(yaml_path).read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not data:
            return DbtProjectConfig()
        return DbtProjectConfig.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as e:
        logger.error(f"Failed to parse dbt_project.yml at {yaml_path}: {e}")
        return DbtProjectConfig()


def parse_sources(sources_yaml: str) -> List[DatasetNode]:
    """Parse __sources.yml → DatasetNodes (M-9, M-10)."""
    datasets = []
    try:
        content = Path(sources_yaml).read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not data:
            return []
            
        config = DbtSourceConfig.model_validate(data)
        
        for source in config.sources:
            for table in source.tables:
                schema_snapshot = {}
                for col in table.columns:
                    name = col.get("name")
                    if name:
                        schema_snapshot[name] = col.get("data_type", "unknown")
                
                if not schema_snapshot:
                    repo_root = Path(sources_yaml).parent.parent.parent
                    csv_candidates = list(repo_root.rglob(f"{table.name}.csv"))
                    if csv_candidates:
                        import csv
                        try:
                            with open(csv_candidates[0], encoding='utf-8') as f:
                                reader = csv.DictReader(f)
                                first_row = next(reader, {})
                                schema_snapshot = {}
                                for col, val in first_row.items():
                                    if not val:
                                        schema_snapshot[col] = "varchar"
                                    elif val.isdigit():
                                        schema_snapshot[col] = "integer"
                                    elif val.replace(".", "", 1).isdigit():
                                        schema_snapshot[col] = "float"
                                    elif "-" in val and ":" in val:
                                        schema_snapshot[col] = "timestamp"
                                    elif "-" in val and len(val) == 10:
                                        schema_snapshot[col] = "date"
                                    else:
                                        schema_snapshot[col] = "varchar"
                        except Exception:
                            pass
                        
                datasets.append(DatasetNode(
                    node_id=f"dataset:{source.name}.{table.name}",
                    name=f"{source.name}.{table.name}",
                    storage_type="table",
                    schema_snapshot=schema_snapshot,
                    freshness_sla=table.loaded_at_field,
                    owner=table.meta.get("owner"),
                    is_source_of_truth=True,
                    source_file=sources_yaml,
                ))
                
    except (OSError, yaml.YAMLError, ValidationError) as e:
        logger.error(f"Failed to parse sources yaml at {sources_yaml}: {e}")
        
    return datasets


def parse_model_yaml(yaml_path: str) -> DbtModelConfig:
    """Parse model .yml files for columns and tests."""
    try:
        content = Path(yaml_path).read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        if not data:
            return DbtModelConfig()
        return DbtModelConfig.model_validate(data)
    except (OSError, yaml.YAMLError, ValidationError) as e:
        logger.error(f"Failed to parse model yaml at {yaml_path}: {e}")
        return DbtModelConfig()

def parse_airflow_dag_yaml(repo_root: str) -> List[Dict]:
    """Parse Airflow yaml config and DAG python files to extract topology.
    Returns dependency edges for ConfiguresEdge entries."""
    import re
    import ast
    edges = []
    
    # Simple parser to find `>>` dependencies in DAG files
    for filepath in Path(repo_root).rglob("*.py"):
        try:
            content = filepath.read_text(encoding="utf-8")
            if "DAG(" not in content and "@dag" not in content:
                continue
                
            # Naive approach: look for x >> y or x.set_downstream(y)
            # In a real system, we'd use tree-sitter or AST to extract the topology
            # For this MVP, we parse simple `task1 >> task2` relationships
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if ">>" in line:
                    parts = [p.strip() for p in line.split(">>")]
                    for j in range(len(parts) - 1):
                        source_task = parts[j].split("[")[-1].strip(" '\"")
                        target_task = parts[j+1].split("[")[0].strip(" '\"")
                        if source_task and target_task and source_task.isidentifier() and target_task.isidentifier():
                            edges.append({
                                "source": f"task:{source_task}",
                                "target": f"task:{target_task}",
                                "file": str(filepath.relative_to(repo_root)),
                                "line": i + 1,
                                "snippet": line.strip()
                            })
        except Exception as e:
            logger.debug(f"Failed to parse DAG {filepath}: {e}")
            
    return edges

# =============================================================================
# Entry Point Detection (F-9, M-8)
# =============================================================================


def detect_entry_points(
    modules: List[ModuleNode],
    dbt_config: DbtProjectConfig,
    repo_root: str,
) -> None:
    """Comprehensive entry point detection mutated in-place on modules.
    
    1. dbt seeds (under seed-paths) → "seed"
    2. dbt marts (materialized: table in config or heuristics) → "mart"
    3. dbt exposures (from model yaml) → "exposure"
    4. Python: if __name__ == "__main__" → "cli"
    5. Python: cli.py, main.py, app.py → "cli"
    6. Airflow: Contains 'DAG(' or '@dag' → "dag"
    7. Test files (test_*.py) → "test"
    """
    import re
    
    seed_paths = dbt_config.seed_paths
    
    for mod in modules:
        path_str = mod.path.lower()
        
        # 7. Test files
        if "test_" in Path(path_str).name or "_test.py" in path_str or "/tests/" in path_str:
            mod.is_entry_point = True
            mod.entry_point_type = "test"
            continue
            
        # 1. Seeds
        if mod.language == "csv" and any(p in path_str for p in seed_paths):
            mod.is_entry_point = True
            mod.entry_point_type = "seed"
            continue
            
        # 2. Marts
        # True dynamic materialization checking requires hitting DataWarehouse, 
        # so we rely on heuristic paths /marts/ or config models.jaffle_shop.marts
        if mod.language == "jinja_sql" and "/marts/" in path_str:
            mod.is_entry_point = True
            mod.entry_point_type = "mart"
            continue
            
        if mod.language == "python":
            full_path = Path(repo_root) / mod.path
            try:
                content = full_path.read_text(encoding="utf-8")
                
                # 6. Airflow DAGs
                if "DAG(" in content or "@dag" in content:
                    mod.is_entry_point = True
                    mod.entry_point_type = "dag"
                    
                    # Extract common metadata
                    meta = {}
                    
                    schedule_match = re.search(r'schedule_interval\s*=\s*(["\'][^"\']+["\']|@\w+|None)', content)
                    if schedule_match:
                        meta['schedule_interval'] = schedule_match.group(1).strip("'\"")
                        
                    retries_match = re.search(r'[\'"]retries[\'"]\s*:\s*(\d+)', content)
                    if retries_match:
                        meta['retries'] = int(retries_match.group(1))
                        
                    owner_match = re.search(r'[\'"]owner[\'"]\s*:\s*[\'"]([^\'"]+)[\'"]', content)
                    if owner_match:
                        meta['owner'] = owner_match.group(1)
                        
                    start_date_match = re.search(r'[\'"]start_date[\'"]\s*:\s*([^\,]+)', content)
                    if start_date_match:
                        meta['start_date'] = start_date_match.group(1).strip()
                        
                    mod.dag_metadata = meta
                    continue
                    
                # 4. python __main__ 
                if "__name__" in content and ('"__main__"' in content or "'__main__'" in content):
                    mod.is_entry_point = True
                    mod.entry_point_type = "cli"
                    continue
                    
                # 5. heuristic names
                name = Path(path_str).name
                if name in ("cli.py", "main.py", "app.py", "manage.py"):
                    mod.is_entry_point = True
                    mod.entry_point_type = "cli"
                    continue
                    
            except OSError:
                pass


def detect_schema_drift(
    sql_columns: List[str], yaml_columns: List[str], sql_file: str, yaml_file: str
) -> List[Dict]:
    """Compare SQL output columns vs YAML documented columns."""
    sql_set, yaml_set = set(sql_columns), set(yaml_columns)
    drifts = []
    
    for col in sql_set - yaml_set:
        drifts.append({"column": col, "issue": "in_sql_not_yaml", "sql_file": sql_file, "yaml_file": yaml_file})
        
    for col in yaml_set - sql_set:
        drifts.append({"column": col, "issue": "in_yaml_not_sql", "sql_file": sql_file, "yaml_file": yaml_file})
        
    return drifts
