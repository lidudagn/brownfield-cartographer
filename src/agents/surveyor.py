"""
Surveyor Agent - The orchestration intelligence for structural analysis.

Takes extracted AST nodes and builds the NetworkX module graph. Computes
git velocity (unique change days), PageRank (module hubs), circular dependencies,
and dead code candidates using 4-factor confidence scoring.
"""

from __future__ import annotations

import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Set, Any, Tuple

import networkx as nx
from tqdm import tqdm

from src.analyzers.dag_config_parser import detect_entry_points
from src.analyzers.tree_sitter_analyzer import TreeSitterAnalyzer
from src.models.schemas import (
    AnalysisCheckpoint,
    CircularDependency,
    CodebaseGraph,
    DatasetNode,
    DbtProjectConfig,
    DeadCodeCandidate,
    Evidence,
    ImportsEdge,
    CallsEdge,
    ModuleNode,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Git Velocity (F-3, R-1)
# =============================================================================


def extract_git_velocity(repo_path: str, filepath: str, days: int = 30) -> Dict[str, Any]:
    """Track UNIQUE DAYS with changes, not commit count."""
    cmd = [
        "git",
        "log",
        "--format=%ad",
        "--date=short",
        f"--since={days} days ago",
        "--",
        filepath,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=repo_path)
        # Log gives one line per commit, we only want unique dates
        dates = set(result.stdout.strip().split("\n"))
        dates.discard("")
        unique_days = len(dates)
    except Exception as e:
        logger.warning(f"Git log failed for {filepath}: {e}")
        unique_days = 0

    return {
        "unique_change_days": unique_days,
        "velocity_score": unique_days / days if days > 0 else 0.0,
        "is_high_velocity": False,  # Evaluated later at repo level
    }


def apply_80_20_velocity(modules: List[ModuleNode]) -> None:
    """Flag top 20% of files by change velocity.

    Tags high-velocity modules by prepending 'HIGH_VELOCITY' to their
    domain_cluster field, which is consumed by the Archivist for the
    CODEBASE.md "High-Velocity Files" section.
    """
    if not modules:
        return

    # Sort modules descending by velocity score
    sorted_mods = sorted(modules, key=lambda m: m.change_velocity_30d, reverse=True)

    # Flag top 20%
    top_n = max(1, int(len(sorted_mods) * 0.2))
    high_velocity_paths: Set[str] = set()
    for mod in sorted_mods[:top_n]:
        if mod.change_velocity_30d > 0:
            existing = mod.domain_cluster or ""
            mod.domain_cluster = f"HIGH_VELOCITY|{existing}" if existing else "HIGH_VELOCITY"
            high_velocity_paths.add(mod.path)

    if high_velocity_paths:
        logger.info(
            "Flagged %d high-velocity files (top 20%%): %s",
            len(high_velocity_paths),
            ", ".join(sorted(high_velocity_paths)),
        )


# =============================================================================
# Circular Dependency Detection (MF-4, C-4)
# =============================================================================


def suggest_cycle_resolution(
    cycle: List[str], graph: nx.DiGraph
) -> str:
    """Analyze cycle and suggest fix based on materials or recent refs."""
    # Assuming dbt defaults to view. A complete fix looks at materializations
    return f"Review refs breaking cycle: {cycle[0]} → {cycle[1]}."


def detect_circular_dependencies(graph: nx.DiGraph) -> List[CircularDependency]:
    """Find cycles in the directed graph."""
    cycles = []
    try:
        # Simple cycle finding for DiGraph
        for cycle in nx.simple_cycles(graph):
            if len(cycle) > 1:  # ignore self-loops
                cycles.append(
                    CircularDependency(
                        cycle_path=cycle.copy(),
                        ref_sites=[],  # Without deep AST traversal again, ref sites are empty
                        suggestion=suggest_cycle_resolution(cycle, graph),
                    )
                )
    except nx.NetworkXNoCycle:
        pass
    except nx.NetworkXNotImplemented:
        pass
    return cycles


# =============================================================================
# Dead Code Detection (MF-3, F-4)
# =============================================================================


def calculate_dead_code_confidence(
    module: ModuleNode, graph: nx.DiGraph
) -> DeadCodeCandidate:
    """4-factor scoring for dead code confidence."""
    confidence = 0.0
    factors = {}
    reasons = []

    # 1. No imports (in_degree=0) - 0.4
    has_no_imports = graph.in_degree(module.path) == 0
    factors["no_imports"] = has_no_imports
    if has_no_imports:
        confidence += 0.4
        reasons.append("No modules import this file")

    # 2. Stale > 90 days (mapped from 30d velocity for now) - 0.3
    is_stale = module.change_velocity_30d == 0.0
    factors["stale_90d"] = is_stale
    if is_stale:
        confidence += 0.3
        reasons.append("No changes in the last 30 days")

    # 3. No tests (using basic heuristic for demonstration) - 0.2
    # In a real run, we'd check if any node of type "test" links to it
    factors["no_tests"] = True
    for src, tgt in graph.edges(module.path):
        src_mod = graph.nodes.get(src, {}).get("node")
        if src_mod and getattr(src_mod, "entry_point_type", None) == "test":
            factors["no_tests"] = False
            break
    if factors["no_tests"]:
        confidence += 0.2
        reasons.append("No test files reference it")

    # 4. Not in exposure - 0.1
    factors["no_exposure"] = not getattr(module, "is_entry_point", False)
    if factors["no_exposure"]:
        confidence += 0.1
        reasons.append("Not listed in any dbt exposure/entry point")

    return DeadCodeCandidate(
        module_path=module.path,
        in_degree=graph.in_degree(module.path) if module.path in graph else 0,
        is_entry_point=module.is_entry_point,
        entry_point_type=module.entry_point_type,
        explanation=". ".join(reasons) + "." if reasons else "Unknown",
        confidence=min(confidence, 1.0),
        factors=factors,
    )


def detect_dead_code(modules: List[ModuleNode], graph: nx.DiGraph) -> List[DeadCodeCandidate]:
    """Find dead code candidates excluding known entry points."""
    candidates = []
    
    for mod in modules:
        # Never flag entry points (seeds, marts, CLI, DAGs, tests)
        if mod.is_entry_point:
            continue
            
        path = mod.path
        
        # Build artifacts
        if any(x in path.lower() for x in ["package-lock", "taskfile", "poetry.lock", "makefile", "dockerfile"]):
            continue
        
        # dbt aware overrides
        if mod.language == "yaml" and ("models/" in path or path.endswith("__sources.yml") or "dbt_project.yml" in path or "packages.yml" in path):
            continue
            
        if "macro" in path or path.startswith("macros/"):
            macro_name = Path(path).stem
            is_used = any(m.language == "jinja_sql" and macro_name in m.public_functions for m in modules)
            if is_used or macro_name.startswith("generate_"):
                continue

        if path in graph and graph.in_degree(path) == 0:
            candidate = calculate_dead_code_confidence(mod, graph)
            if candidate.confidence > 0.0:
                candidates.append(candidate)
                
    return candidates


# =============================================================================
# Graph Building & PageRank
# =============================================================================


def get_evidence_line(repo_path: str, source_path: str, search_target: str) -> Evidence:
    """Helper to pinpoint the line number of an import or call in the source file."""
    full_path = Path(repo_path) / source_path
    ev = Evidence(file_path=source_path, line_start=1, line_end=1, snippet=search_target, analysis_method="regex")
    if not full_path.exists():
        return ev
        
    stem = Path(search_target).stem
    is_macro = search_target.startswith("macros/")
    
    try:
        lines = full_path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            match = False
            if source_path.endswith(".sql"):
                if is_macro:
                    if f"{stem}(" in line:
                        match = True
                elif search_target.startswith("source:"):
                    parts = search_target.replace("source:", "").split(".")
                    if len(parts) == 2 and f"source('{parts[0]}', '{parts[1]}')" in line:
                        match = True
                    elif search_target in line:
                        match = True
                else:
                    # Look for ref('stem') exactly, avoiding CTE aliases
                    if f"ref('{stem}')" in line or f'ref("{stem}")' in line:
                        match = True
            else:
                if search_target in line or stem in line:
                    match = True
                    
            if match:
                ev.line_start = i + 1
                ev.line_end = i + 1
                ev.snippet = line.strip()
                break
    except Exception:
        pass
    return ev


def build_module_graph(modules: List[ModuleNode], repo_path: str = ".") -> Tuple[nx.DiGraph, List[ImportsEdge], List[CallsEdge]]:
    """Construct a NetworkX DiGraph where nodes are ModuleObjects and edges are Imports/Calls."""
    G = nx.DiGraph()
    imports_edges = []
    calls_edges = []
    
    # Add all modules as nodes
    for mod in modules:
        G.add_node(mod.path, node=mod)
        
    # Add imports as directed edges
    for mod in modules:
        resolved_imports = []
        for imp in mod.imports:
            target = imp
            if not target.endswith('.py') and not target.endswith('.sql'):
                # Heuristic lookup for dbt refs or python base names
                for m in modules:
                    if m.language == "yaml" and not imp.startswith("configures") and not imp.startswith("source:"):
                        continue  # Never resolve standard code refs to yaml files
                    base = Path(m.path).stem
                    if base == imp or target == f"__dbt_ref__{base}":
                        target = m.path
                        break
            
            resolved_imports.append(target)
            if target != imp or target in G:
                G.add_edge(mod.path, target)
                imports_edges.append(ImportsEdge(
                    source=mod.path,
                    target=target,
                    evidence=get_evidence_line(repo_path, mod.path, target)
                ))
        
        # Replace the shortnames with standard paths for Phase 2 compatibility
        mod.imports = list(set(resolved_imports))
        
        # Link macros (CALLS edge)
        for func in mod.called_macros:
            macro_target = f"macros/{func}.sql"
            if any(m.path == macro_target for m in modules):
                G.add_edge(mod.path, macro_target)
                calls_edges.append(CallsEdge(
                    source=mod.path,
                    target=macro_target,
                    evidence=get_evidence_line(repo_path, mod.path, macro_target)
                ))
                
    return G, imports_edges, calls_edges


def run_pagerank(graph: nx.DiGraph) -> None:
    """Run PageRank and attach scores to nodes.
    Reverse the graph so that downstream hubs (who are imported locally) get the high scores.
    """
    try:
        pr = nx.pagerank(graph.reverse())
        for node, score in pr.items():
            graph.nodes[node]["pagerank"] = score
            mod = graph.nodes[node].get("node")
            if mod:
                mod.pagerank = score
    except nx.NetworkXError as e:
        logger.warning(f"PageRank failed: {e}")
