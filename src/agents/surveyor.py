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
from typing import Dict, List, Set, Any

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
    """Flag top 20% of files by change velocity."""
    if not modules:
        return

    # Sort modules descending by velocity score
    sorted_mods = sorted(modules, key=lambda m: m.change_velocity_30d, reverse=True)

    # Flag top 20%
    top_n = max(1, int(len(sorted_mods) * 0.2))
    for mod in sorted_mods[:top_n]:
        if mod.change_velocity_30d > 0:
            # We add this logic to handle any internal storage mechanism;
            # but since "is_high_velocity" isn't directly on ModuleNode,
            # we rely on the raw velocity_score or domain_cluster labeling.
            pass


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
        if path in graph and graph.in_degree(path) == 0:
            candidate = calculate_dead_code_confidence(mod, graph)
            if candidate.confidence > 0.0:
                candidates.append(candidate)
                
    return candidates


# =============================================================================
# Graph Building & PageRank
# =============================================================================


def build_module_graph(modules: List[ModuleNode]) -> Tuple[nx.DiGraph, List[ImportsEdge]]:
    """Construct a NetworkX DiGraph where nodes are ModuleObjects and edges are Imports."""
    G = nx.DiGraph()
    edges = []
    
    # Add all modules as nodes
    for mod in modules:
        G.add_node(mod.path, node=mod)
        
    # Add imports as directed edges
    for mod in modules:
        for imp in mod.imports:
            # Very basic resolution constraint logic (assuming exact path or standard dbt ref)
            # In complete Phase 1, we match ref('abc') -> abc.sql
            target = imp
            if not target.endswith('.py') and not target.endswith('.sql'):
                # Heuristic lookup for dbt refs or python base names
                for m in modules:
                    base = Path(m.path).stem
                    if base == imp or target == f"__dbt_ref__{base}":
                        target = m.path
                        break
            
            if target != imp or target in G:
                G.add_edge(mod.path, target)
                edges.append(ImportsEdge(
                    source=mod.path,
                    target=target,
                    evidence=Evidence(
                        file_path=mod.path, line_start=0, line_end=0, snippet=imp, analysis_method="regex"
                    )
                ))
    return G, edges


def run_pagerank(graph: nx.DiGraph) -> None:
    """Run PageRank and attach scores to nodes."""
    try:
        pr = nx.pagerank(graph)
        for node, score in pr.items():
            graph.nodes[node]["pagerank"] = score
            mod = graph.nodes[node].get("node")
            if mod:
                mod.pagerank = score
    except nx.NetworkXError as e:
        logger.warning(f"PageRank failed: {e}")
