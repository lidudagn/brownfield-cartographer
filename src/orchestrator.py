"""
Orchestrator — The nervous system traversing the codebase.

Wires all parsers and analyzers into a 12-step pipeline:
1. File discovery
2. Tree-sitter AST parallel processing
3. SQL Lineage
4. DAG config & Schema snapshots
5. Entry point detection
6. NetworkX module graph
7. Git velocity (unique change days)
8. PageRank & SCC Circular deps
9. Dead code confidence
10. Hydrologist lineage graph
11. Semanticist LLM analysis
12. Archivist artifact generation
"""

from __future__ import annotations

import glob
import json
import logging
import subprocess
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
    detect_dead_code,
    extract_git_velocity,
    run_pagerank,
)
from src.agents.hydrologist import Hydrologist
from src.agents.archivist import ArchivistAgent
try:
    from src.agents.semanticist import SemanticistAgent
    _HAS_SEMANTICIST = True
except ImportError:
    _HAS_SEMANTICIST = False
from src.analyzers.dag_config_parser import (
    detect_entry_points,
    detect_schema_drift,
    parse_dbt_project,
    parse_model_yaml,
    parse_sources,
)
from src.analyzers.sql_lineage import (
    detect_dialect,
    extract_sql_dependencies,
)
from src.analyzers.tree_sitter_analyzer import TreeSitterAnalyzer
from src.graph.knowledge_graph import KnowledgeGraphWrapped, visualize_interactive_lineage
from src.models.schemas import (
    AnalysisCheckpoint,
    CodebaseGraph,
    ConfiguresEdge,
    DatasetNode,
    DbtProjectConfig,
    DeadCodeCandidate,
    Evidence,
    FunctionNode,
    ImportsEdge,
    CallsEdge,
    ProducesEdge,
    ConsumesEdge,
    ModuleNode,
    TransformationNode,
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
    patterns = ["**/*.py", "**/*.sql", "**/*.yml", "**/*.yaml", "**/*.csv", "**/*.ipynb", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx"]
    files = []
    for pattern in patterns:
        files.extend(glob.glob(str(repo / pattern), recursive=True))
        
    # Ignore dbt specific directories that aren't source code
    exclude_dirs = ["target/", "dbt_packages/", "logs/", "venv/", ".env/", "node_modules/", "__pycache__/", ".git/", "site-packages/"]
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
        if "macros/" in mod.path.replace("\\", "/"):
            continue

        # Read each file to get accurate line count (Fix for stale raw_sql)
        try:
            mod_sql = (repo / mod.path).read_text(encoding="utf-8")
            total_lines = len(mod_sql.splitlines())
        except OSError:
            total_lines = mod.lines_of_code

        transformations.append(TransformationNode(
            node_id=f"transformation:{Path(mod.path).stem}",
            name=Path(mod.path).stem,
            source_datasets=mod.imports,
            target_datasets=[f"dataset:{Path(mod.path).stem}"],
            transformation_type="select",
            source_file=mod.path,
            line_range=(1, total_lines),
            column_lineage=[lin for lin in lineages if lin.source_file == mod.path]
        ))

    # Step 4: DAG Config & Source Parsing (M-5)
    dbt_config = DbtProjectConfig()
    dbt_project_path = repo / "dbt_project.yml"
    if dbt_project_path.exists():
        dbt_config = parse_dbt_project(str(dbt_project_path))
        
    datasets = []
    for src_yml in list(repo.glob("**/__sources.yml")) + list(repo.glob("**/_sources.yml")):
        new_datasets = parse_sources(str(src_yml))
        for d in new_datasets:
            d.source_file = str(Path(d.source_file).relative_to(repo.absolute())) if Path(d.source_file).is_absolute() else d.source_file
            datasets.append(d)

    # Step 5: Entry Point Detection (F-9)
    detect_entry_points(modules, dbt_config, repo_path)

    # Step 5.5: Schema Drift Detection — compare SQL vs YAML columns
    schema_drifts = []
    for mod in sql_modules:
        model_name = Path(mod.path).stem
        # Find corresponding YAML config
        yaml_candidates = list(repo.glob(f"**/{model_name}.yml"))
        if not yaml_candidates:
            continue
        model_yaml = parse_model_yaml(str(yaml_candidates[0]))
        yaml_columns = []
        for m_def in model_yaml.models:
            if m_def.name == model_name:
                yaml_columns = [c.name for c in m_def.columns]
                break
        # Get SQL output columns from column lineage
        sql_columns = list(set(
            cl.target_column for cl in lineages if cl.source_file == mod.path
        ))
        if yaml_columns and sql_columns:
            drifts = detect_schema_drift(sql_columns, yaml_columns, mod.path, str(yaml_candidates[0]))
            schema_drifts.extend(drifts)
    if schema_drifts:
        logger.warning(f"Schema drift detected: {len(schema_drifts)} column mismatches")
        for drift in schema_drifts[:5]:
            logger.warning(f"  {drift['column']}: {drift['issue']} ({drift['sql_file']} vs {drift['yaml_file']})")

    # Step 6: Git Velocity (F-3, R-1)
    for mod in tqdm(modules, desc="Git Velocity"):
        vel_data = extract_git_velocity(repo_path, mod.path, days=days)
        mod.change_velocity_30d = vel_data["velocity_score"]
        
    apply_80_20_velocity(modules)

    # Step 6.5: Populate last_modified from git log
    for mod in modules:
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--format=%aI", "--", mod.path],
                capture_output=True, text=True, cwd=repo_path,
            )
            date_str = result.stdout.strip()
            if date_str:
                mod.last_modified = date_str
        except Exception:
            pass

    # Step 7: Build Module Graph
    G, imports_edges, calls_edges = build_module_graph(modules, repo_path=repo_path)
    
    # Step 8: PageRank & Circular Dependencies (MF-4)
    run_pagerank(G)
    hydro = Hydrologist()
    cycles = hydro.detect_circular_dependencies(G)
    if cycles:
        logger.warning(f"Detected {len(cycles)} circular dependencies!")
        
    # Step 9: Dead Code Candidate Scoring (MF-3, F-4)
    dead_code = detect_dead_code(modules, G)
    for dcc in dead_code:
        # Mark on the module
        if dcc.module_path in modules_dict:
            modules_dict[dcc.module_path].is_dead_code_candidate = True

    # Step 9.5: Produces and Consumes Edges
    produces_edges = []
    consumes_edges = []
    for t in transformations:
        raw_text = None
        try:
            raw_text = (repo / t.source_file).read_text(encoding="utf-8")
        except OSError:
            pass
            
        for sd in t.source_datasets:
            snippet = f"consumes {sd}"
            start_line = t.line_range[0]
            if raw_text:
                search_term = sd
                if sd.startswith("source:"):
                    parts = sd.replace("source:", "").split(".")
                    if len(parts) == 2:
                        search_term = parts[1]
                else:
                    search_term = Path(sd).stem
                
                for i, line in enumerate(raw_text.splitlines()):
                    if search_term in line:
                        snippet = line.strip()
                        start_line = i + 1
                        break
            if sd.startswith("source:"):
                sd_id = f"dataset:{sd.replace('source:', '')}"
            else:
                sd_id = f"dataset:{Path(sd).stem}"
                
            consumes_edges.append(ConsumesEdge(
                source=t.node_id, target=sd_id, 
                evidence=Evidence(file_path=t.source_file, line_start=start_line, line_end=start_line, snippet=snippet, analysis_method="sqlglot")
            ))
            
        for td in t.target_datasets:
            snippet = f"produces {td}"
            start_line = t.line_range[0]
            if raw_text:
                for i, line in enumerate(raw_text.splitlines()):
                    if line.strip() and not line.strip().startswith("--"):
                        snippet = line.strip()
                        start_line = i + 1
                        break
            produces_edges.append(ProducesEdge(
                source=t.node_id, target=td, 
                evidence=Evidence(file_path=t.source_file, line_start=start_line, line_end=start_line, snippet=snippet, analysis_method="sqlglot")
            ))

    # Step 9.7: Populate FunctionNodes from Python modules
    function_nodes = []
    for mod in modules:
        if mod.language == "python":
            for func_sig in mod.public_functions:
                func_name = func_sig.split("(")[0] if "(" in func_sig else func_sig
                # Count how many other modules reference this function
                call_count = 0
                for other_mod in modules:
                    if other_mod.path != mod.path:
                        try:
                            other_src = (repo / other_mod.path).read_text(encoding="utf-8")
                            if func_name in other_src:
                                call_count += 1
                        except OSError:
                            pass
                function_nodes.append(FunctionNode(
                    qualified_name=f"{mod.path}::{func_name}",
                    parent_module=mod.path,
                    signature=func_sig,
                    is_public_api=True,
                    call_count_within_repo=call_count,
                ))

    # Step 9.8: Create ConfiguresEdges from YAML → model relationships
    configures_edges = []
    for mod in modules:
        if mod.language == "yaml":
            for imp in mod.imports:
                if imp.startswith("configures:"):
                    model_name = imp.replace("configures:", "")
                    # Find the target module
                    target_path = None
                    for m in modules:
                        if Path(m.path).stem == model_name:
                            target_path = m.path
                            break
                    if target_path:
                        configures_edges.append(ConfiguresEdge(
                            source=mod.path,
                            target=target_path,
                            evidence=Evidence(
                                file_path=mod.path,
                                line_start=1,
                                line_end=1,
                                snippet=f"configures model: {model_name}",
                                analysis_method="yaml_parse",
                            ),
                        ))

    # Step 10: Serialization & Vis (F-8, M-11)
    cg = CodebaseGraph(
        repo_path=repo_path,  # Use the path as provided by the user
        analysis_timestamp=datetime.now().isoformat(),
        modules=modules,
        datasets=datasets,
        functions=function_nodes,
        transformations=transformations,
        imports_edges=imports_edges,
        calls_edges=calls_edges,
        produces_edges=produces_edges,
        consumes_edges=consumes_edges,
        configures_edges=configures_edges,
        unresolved_refs=unresolved_refs,
        dead_code_candidates=dead_code,
        circular_dependencies=cycles,
        analysis_errors=[]  # Gathered per module
    )
    
    # Step 11: Wire Hydrologist — build lineage graph and run analytics
    hydro.build_lineage_graph(cg)
    lineage_stats = hydro.get_statistics()
    sources = hydro.find_sources()
    sinks = hydro.find_sinks()
    logger.info(f"Lineage stats: {lineage_stats}")
    logger.info(f"Data sources: {sources}")
    logger.info(f"Data sinks: {sinks}")
    
    # Step 11.5: Wire Semanticist — populate purpose statements, domain clusters, and answer Day-One questions
    day_one_answers = []
    if _HAS_SEMANTICIST:
        try:
            semanticist = SemanticistAgent(repo_root=repo_path)
            semanticist.run(cg)
            day_one_answers = semanticist.answer_day_one_questions(cg)
        except Exception as e:
            logger.warning(f"Semanticist failed (non-fatal): {e}")
    else:
        logger.info("SemanticistAgent not available (missing deps). Skipping.")
    
    # Step 12: Archivist — generate all living artifacts
    archivist = ArchivistAgent()
    
    # Feed pipeline trace entries to the Archivist
    trace_entries = [
        {"action": "file_discovery", "files_found": len(files), "confidence": 1.0, "evidence_source": "static_analysis", "timestamp": datetime.now().isoformat()},
        {"action": "ast_parsing", "modules_parsed": len(modules), "parse_errors": sum(1 for m in modules if not m.is_complete_parse), "confidence": 1.0, "evidence_source": "static_analysis", "timestamp": datetime.now().isoformat()},
        {"action": "sql_lineage", "sql_files_analyzed": len(sql_modules), "column_lineages_extracted": len(lineages), "unresolved_refs": len(unresolved_refs), "confidence": 1.0, "evidence_source": "static_analysis", "timestamp": datetime.now().isoformat()},
        {"action": "entry_point_detection", "entry_points": len([m for m in modules if m.is_entry_point]), "confidence": 1.0, "evidence_source": "static_analysis", "timestamp": datetime.now().isoformat()},
        {"action": "git_velocity", "high_velocity_files": len([m for m in modules if m.dag_metadata.get("is_high_velocity")]), "confidence": 1.0, "evidence_source": "static_analysis", "timestamp": datetime.now().isoformat()},
        {"action": "graph_analysis", "nodes": G.number_of_nodes(), "edges": G.number_of_edges(), "circular_deps": len(cycles), "dead_code_candidates": len(dead_code), "confidence": 1.0, "evidence_source": "static_analysis", "timestamp": datetime.now().isoformat()},
        {"action": "hydrologist", "lineage_nodes": lineage_stats["num_nodes"], "lineage_edges": lineage_stats["num_edges"], "sources": len(sources), "sinks": len(sinks), "confidence": 1.0, "evidence_source": "static_analysis", "timestamp": datetime.now().isoformat()},
    ]
    archivist.add_trace_entries(trace_entries)
    
    # Get semanticist budget if available
    semanticist_budget = None
    if _HAS_SEMANTICIST:
        try:
            semanticist_budget = semanticist.budget  # type: ignore[possibly-undefined]
        except (NameError, Exception):
            pass
    
    archivist.run(
        graph=cg,
        hydro=hydro,
        day_one_answers=day_one_answers,
        semanticist_budget=semanticist_budget,
        output_dir=str(out),
    )
    
    # Save graph artifacts and visualization
    wrapper = KnowledgeGraphWrapped(cg)
    png_path = out / "module_graph.png"
    wrapper.save_artifacts(out)
    wrapper.visualize(png_path)
    
    # Generate semantic index (vector store of purpose statements)
    archivist.generate_semantic_index(cg, str(out))
    
    # Save the strictly lineage-based interactive graph
    visualize_interactive_lineage(hydro.graph, out / "lineage_graph.html")

    
    duration = time.time() - start_time
    logger.info(f"Analysis complete in {duration:.2f}s. Saved to {output_dir}")
    
    # Save last commit SHA for incremental mode
    try:
        result_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=repo_path,
        )
        if result_sha.returncode == 0:
            (out / "last_commit.txt").write_text(result_sha.stdout.strip())
    except Exception:
        pass  # Not a git repo or git not available
    
    # Cleanup checkpoint if successful (SR-1)
    if checkpoint_file.exists():
        checkpoint_file.unlink()
        
    return cg


def run_incremental(
    repo_path: str,
    output_dir: str,
    dialect: str = "postgres",
    workers: int = 4,
    days: int = 30,
    verbose: bool = False,
) -> CodebaseGraph | None:
    """Run incremental analysis — re-analyze only changed files.
    
    Steps:
    1. Load previous module_graph.json
    2. Read last commit SHA from last_commit.txt
    3. Run git diff to find changed files
    4. Re-parse only changed files
    5. Merge updated ModuleNodes into existing graph
    6. Rebuild all edges
    7. Recompute PageRank
    8. Regenerate all artifacts via Archivist
    
    Falls back to full analysis on any error.
    """
    out = Path(output_dir)
    graph_path = out / "module_graph.json"
    commit_path = out / "last_commit.txt"
    
    try:
        # Validate prerequisites
        if not graph_path.exists():
            raise FileNotFoundError(f"No previous analysis found at {graph_path}")
        if not commit_path.exists():
            raise FileNotFoundError("No last_commit.txt found")
        
        last_sha = commit_path.read_text().strip()
        
        # Get changed files via git diff
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", f"{last_sha}..HEAD"],
            capture_output=True, text=True, cwd=repo_path, check=True,
        )
        changed_files = [f for f in diff_result.stdout.strip().split("\n") if f]
        
        if not changed_files:
            logger.info("No files changed since last analysis. Nothing to update.")
            return None
        
        logger.info(f"Incremental update: {len(changed_files)} files changed since {last_sha[:8]}")
        
        # Load previous graph
        wrapper = KnowledgeGraphWrapped.load(graph_path)
        cg = wrapper.codebase
        
        # Re-parse changed files
        analyzer = TreeSitterAnalyzer()
        existing_paths = {m.path for m in cg.modules}
        
        for filepath in changed_files:
            full_path = Path(repo_path) / filepath
            if not full_path.exists():
                # File was deleted — remove from graph
                cg.modules = [m for m in cg.modules if m.path != filepath]
                continue
            
            # Check extension
            if full_path.suffix not in (".py", ".sql", ".yml", ".yaml", ".csv"):
                continue
            
            try:
                mod = analyzer.analyze_module(filepath, repo_path)
                # Replace or add module
                cg.modules = [m for m in cg.modules if m.path != filepath]
                cg.modules.append(mod)
            except Exception as e:
                logger.warning(f"Failed to re-parse {filepath}: {e}")
        
        # Rebuild edges (imports)
        import networkx as nx
        G, imports_edges, calls_edges = build_module_graph(cg.modules, repo_path=repo_path)
        cg.imports_edges = imports_edges
        cg.calls_edges = calls_edges
        run_pagerank(G)
        
        # Rebuild lineage
        hydro = Hydrologist()
        hydro.build_lineage_graph(cg)
        
        # Re-run Archivist
        archivist = ArchivistAgent()
        archivist.add_trace_entries([{
            "action": "incremental_update",
            "changed_files": len(changed_files),
            "previous_sha": last_sha[:8],
            "confidence": 1.0,
            "evidence_source": "static_analysis",
            "timestamp": datetime.now().isoformat(),
        }])
        archivist.run(
            graph=cg,
            hydro=hydro,
            day_one_answers=[],
            semanticist_budget=None,
            output_dir=str(out),
        )
        
        # Save updated graph
        wrapper_new = KnowledgeGraphWrapped(cg)
        wrapper_new.save_artifacts(out)
        wrapper_new.visualize(out / "module_graph.png")
        
        visualize_interactive_lineage(hydro.graph, out / "lineage_graph.html")

        
        # Update last commit
        sha_result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=repo_path,
        )
        if sha_result.returncode == 0:
            commit_path.write_text(sha_result.stdout.strip())
        
        logger.info(f"Incremental update complete. {len(changed_files)} files re-analyzed.")
        return cg
        
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError) as e:
        logger.warning(f"Incremental update failed ({e}), falling back to full analysis.")
        return run_analysis(
            repo_path=repo_path,
            output_dir=output_dir,
            dialect=dialect,
            workers=workers,
            days=days,
            verbose=verbose,
        )
