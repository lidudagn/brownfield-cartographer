"""
Orchestrator — The nervous system traversing the codebase.

Wires all parsers and analyzers into a 10-step pipeline:
1. File discovery
2. Tree-sitter AST parallel processing
3. SQL Lineage
4. DAG config & Schema snapshots
5. Entry point detection
6. NetworkX module graph
7. Git velocity (unique change days)
8. PageRank & SCC Circular deps
9. Dead code confidence
10. Serialization & Visualization
"""

from __future__ import annotations

import glob
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

from tqdm import tqdm

from src.agents.surveyor import (
    apply_80_20_velocity,
    build_module_graph,
    calculate_dead_code_confidence,
    detect_circular_dependencies,
    detect_dead_code,
    extract_git_velocity,
    run_pagerank,
)
from src.analyzers.dag_config_parser import (
    detect_entry_points,
    parse_dbt_project,
    parse_sources,
)
from src.analyzers.sql_lineage import (
    detect_dialect,
    extract_sql_dependencies,
)
from src.analyzers.tree_sitter_analyzer import TreeSitterAnalyzer
from src.graph.knowledge_graph import KnowledgeGraphWrapped
from src.models.schemas import (
    AnalysisCheckpoint,
    CodebaseGraph,
    DatasetNode,
    DbtProjectConfig,
    DeadCodeCandidate,
    Evidence,
    ImportsEdge,
    ModuleNode,
    UnresolvedReference,
)

logger = logging.getLogger(__name__)


def run_analysis(
    repo_path: str,
    output_dir: str,
    dialect: str = "postgres",
    workers: int = 4,
    days: int = 30,
    dry_run: bool = False,
    verbose: bool = False,
) -> CodebaseGraph | None:
    """Run the 10-step Surveyor orchestration pipeline."""
    start_time = time.time()
    
    repo = Path(repo_path)
    if not repo.exists() or not repo.is_dir():
        logger.error(f"Repository path does not exist: {repo_path}")
        return None
        
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    
    # Optional checkpoint persistence (SR-1)
    checkpoint_file = out / "checkpoint.json"

    # Step 1: File Discovery
    patterns = ["**/*.py", "**/*.sql", "**/*.yml", "**/*.yaml", "**/*.csv"]
    files = []
    for pattern in patterns:
        files.extend(glob.glob(str(repo / pattern), recursive=True))
        
    # Ignore dbt specific directories that aren't source code
    exclude_dirs = ["target/", "dbt_packages/", "logs/", "venv/", ".env/"]
    files = [
        f for f in files 
        if not any(ex in f for ex in exclude_dirs)
    ]
    
    if dry_run:
        logger.info(f"DRY RUN: Discovered {len(files)} files to analyze:")
        for f in sorted(files):
            logger.info(f"  - {Path(f).relative_to(repo)}")
        return None
        
    logger.info(f"Found {len(files)} source files. Starting analysis with {workers} workers.")

    # Step 2: Parallel Tree-Sitter parsing (M-12)
    analyzer = TreeSitterAnalyzer()
    modules_dict: Dict[str, ModuleNode] = {}
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(
                analyzer.analyze_module, 
                str(Path(f).relative_to(repo)), 
                repo_path
            ): str(Path(f).relative_to(repo))
            for f in files
        }
        
        for idx, future in enumerate(tqdm(as_completed(futures), total=len(futures), desc="AST Parsing")):
            filepath = futures[future]
            try:
                mod = future.result()
                modules_dict[filepath] = mod
            except Exception as e:
                logger.error(f"Fatal error analyzing {filepath}: {e}")
                
            # SR-1 Checkpoint save every 100 files
            if idx > 0 and idx % 100 == 0:
                ckpt = AnalysisCheckpoint(
                    completed_files=list(modules_dict.keys()),
                    checkpoint_time=datetime.now().isoformat(),
                )
                checkpoint_file.write_text(ckpt.model_dump_json())

    modules = list(modules_dict.values())

    # Step 3: SQL Lineage & Jinja Preprocessing (MF-1)
    if dialect == "auto":
        dbt_proj_path = repo / "dbt_project.yml"
        dialect = detect_dialect(str(dbt_proj_path)) if dbt_proj_path.exists() else "postgres"
        logger.info(f"Auto-detected SQL dialect: {dialect}")
        
    lineages = []
    unresolved_refs = []
    sql_modules = [m for m in modules if m.language == "jinja_sql"]
    
    for mod in tqdm(sql_modules, desc="SQL Lineage"):
        try:
            raw_sql = (repo / mod.path).read_text(encoding="utf-8")
            deps, col_lineage, _, unres = extract_sql_dependencies(raw_sql, mod.path, dialect)
            
            # Append detailed extraction back to the module
            mod.imports = list(set(mod.imports + deps))
            lineages.extend(col_lineage)
            unresolved_refs.extend(unres)
        except OSError:
            pass
            
    # Combine transformations
    transformations = []
    for mod in sql_modules:
        transformations.append({
            "name": Path(mod.path).stem,
            "source_datasets": mod.imports,
            "target_datasets": [f"table_{Path(mod.path).stem}"],
            "transformation_type": "select",
            "source_file": mod.path,
            "line_range": (0, 0),
            "column_lineage": [lin for lin in lineages if lin.source_file == mod.path]
        })

    # Step 4: DAG Config & Source Parsing (M-5)
    dbt_config = DbtProjectConfig()
    dbt_project_path = repo / "dbt_project.yml"
    if dbt_project_path.exists():
        dbt_config = parse_dbt_project(str(dbt_project_path))
        
    datasets = []
    for src_yml in repo.glob("**/__sources.yml"):
        datasets.extend(parse_sources(str(src_yml)))

    # Step 5: Entry Point Detection (F-9)
    detect_entry_points(modules, dbt_config, repo_path)

    # Step 6: Git Velocity (F-3, R-1)
    for mod in tqdm(modules, desc="Git Velocity"):
        vel_data = extract_git_velocity(repo_path, mod.path, days=days)
        mod.change_velocity_30d = vel_data["velocity_score"]
        
    apply_80_20_velocity(modules)

    # Step 7: Build Module Graph
    G, imports_edges = build_module_graph(modules)
    
    # Step 8: PageRank & Circular Dependencies (MF-4)
    run_pagerank(G)
    cycles = detect_circular_dependencies(G)
    if cycles:
        logger.warning(f"Detected {len(cycles)} circular dependencies!")
        
    # Step 9: Dead Code Candidate Scoring (MF-3, F-4)
    dead_code = detect_dead_code(modules, G)
    for dcc in dead_code:
        # Mark on the module
        if dcc.module_path in modules_dict:
            modules_dict[dcc.module_path].is_dead_code_candidate = True

    # Step 10: Serialization & Vis (F-8, M-11)
    cg = CodebaseGraph(
        repo_path=str(repo.absolute()),
        analysis_timestamp=datetime.now().isoformat(),
        modules=modules,
        datasets=datasets,
        functions=[],  # We have functions in ModuleNode.public_functions
        transformations=[],  # Would properly map to TransformationNode in production
        imports_edges=imports_edges,
        unresolved_refs=unresolved_refs,
        dead_code_candidates=dead_code,
        circular_dependencies=cycles,
        analysis_errors=[]  # Gathered per module
    )
    
    wrapper = KnowledgeGraphWrapped(cg)
    json_path = out / "module_graph.json"
    png_path = out / "module_graph.png"
    
    wrapper.save(json_path)
    wrapper.visualize(png_path)
    
    duration = time.time() - start_time
    logger.info(f"Analysis complete in {duration:.2f}s. Saved to {output_dir}")
    
    # Cleanup checkpoint if successful (SR-1)
    if checkpoint_file.exists():
        checkpoint_file.unlink()
        
    return cg
