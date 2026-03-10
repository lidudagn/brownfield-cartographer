"""
Knowledge Graph wrapper for NetworkX and serialization.

Stores all extracted nodes and edges. Serializes to `.cartography/module_graph.json`
and generates `module_graph.png` visualization using PageRank (size) and Velocity (color).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import networkx as nx

from src.models.schemas import CodebaseGraph

logger = logging.getLogger(__name__)


# =============================================================================
# Graph Visualization (F-8)
# =============================================================================


def visualize_graph(graph: nx.DiGraph, output_path: Path) -> None:
    """
    Generate graph visualization with:
    - Node size = PageRank score (normalized)
    - Node color = git velocity (red=high, blue=low)
    - Labels = module basenames
    - Edge thickness = import count/weight
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # For headless saving
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not installed; skipping visualization")
        return

    # Basic layout
    fig, ax = plt.subplots(1, 1, figsize=(16, 12))
    pos = nx.spring_layout(graph, k=2.0, iterations=50, seed=42)

    # 1. Node size = PageRank (normalized 300-3000)
    # If pagerank hasn't been computed, compute it now
    try:
        pr = nx.pagerank(graph)
    except Exception:
        pr = {n: 0.1 for n in graph.nodes()}
        
    sizes = [300 + pr.get(n, 0) * 27000 for n in graph.nodes()]

    # 2. Node color = velocity (blue=low → red=high)
    velocities = []
    for n in graph.nodes():
        node_attr = graph.nodes[n].get("node")
        if node_attr and hasattr(node_attr, "change_velocity_30d"):
            velocities.append(node_attr.change_velocity_30d)
        else:
            velocities.append(0.0)
            
    norm = plt.Normalize(vmin=0, vmax=max(velocities) if velocities else 1)

    # 3. Edge thickness = weight
    widths = [graph.edges[e].get("weight", 1) for e in graph.edges()]

    # Draw everything
    nx.draw(
        graph,
        pos,
        ax=ax,
        node_size=sizes,
        node_color=[norm(v) for v in velocities],
        cmap=plt.cm.RdYlBu_r,
        width=widths,
        with_labels=True,
        labels={n: Path(str(n)).stem for n in graph.nodes()},
        font_size=8,
        edge_color="#666666",
        alpha=0.9,
    )

    # Add colorbar
    sm = plt.cm.ScalarMappable(cmap=plt.cm.RdYlBu_r, norm=norm)
    plt.colorbar(sm, ax=ax, label="Git Velocity (unique change days/30d)")
    
    plt.title("Codebase Module Graph\nNode Size = PageRank, Node Color = Git Velocity")
    
    # Save to disk
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.close()
    
    logger.info(f"Generated visualization at {output_path}")


# =============================================================================
# Graph Wrapper
# =============================================================================


class KnowledgeGraphWrapped:
    """Wrapper around NetworkX to serialize CodebaseGraph to/from JSON."""
    
    def __init__(self, codebase: CodebaseGraph):
        self.codebase = codebase
        self.nx_graph = nx.DiGraph()
        self._build_nx()
        
    def _build_nx(self) -> None:
        """Convert Pydantic structure to NetworkX."""
        for mod in self.codebase.modules:
            self.nx_graph.add_node(mod.path, **mod.model_dump())
            
        for edge in self.codebase.imports_edges:
            self.nx_graph.add_edge(edge.source, edge.target, weight=edge.weight)
            
    def visualize(self, output_path: Path) -> None:
        """Expose visualization externally."""
        visualize_graph(self.nx_graph, output_path)

    def save(self, filepath: Path) -> None:
        """Serialize CodebaseGraph to JSON."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        # We save the raw Pydantic JSON dump, which is what downstream agents want
        json_data = self.codebase.model_dump_json(indent=2)
        filepath.write_text(json_data, encoding="utf-8")
        logger.info(f"Saved {len(self.codebase.modules)} modules to {filepath}")

    def save_artifacts(self, out_dir: Path) -> None:
        """Serialize CodebaseGraph into distinct JSON artifacts for downstream agents."""
        out_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. module_graph.json
        mg_data = {
            "repo_path": self.codebase.repo_path,
            "analysis_timestamp": self.codebase.analysis_timestamp,
            "modules": [m.model_dump() for m in self.codebase.modules],
            "imports_edges": [e.model_dump() for e in self.codebase.imports_edges],
            "calls_edges": [e.model_dump() for e in self.codebase.calls_edges],
            "functions": [f.model_dump() for f in self.codebase.functions]
        }
        (out_dir / "module_graph.json").write_text(json.dumps(mg_data, indent=2), encoding="utf-8")
        
        # 2. lineage_graph.json
        lg_data = {
            "transformations": [t.model_dump() for t in self.codebase.transformations],
            "produces_edges": [e.model_dump() for e in self.codebase.produces_edges],
            "consumes_edges": [e.model_dump() for e in self.codebase.consumes_edges]
        }
        (out_dir / "lineage_graph.json").write_text(json.dumps(lg_data, indent=2), encoding="utf-8")
        
        # 3. dataset_registry.json
        dr_data = {
            "datasets": [d.model_dump() for d in self.codebase.datasets]
        }
        (out_dir / "dataset_registry.json").write_text(json.dumps(dr_data, indent=2), encoding="utf-8")
        
        # 4. analysis_report.json
        ar_data = {
            "summary": {
                "modules_analyzed": len(self.codebase.modules),
                "datasets_discovered": len(self.codebase.datasets),
                "transformations": len(self.codebase.transformations),
                "macros": len([m for m in self.codebase.modules if "macro" in m.path])
            },
            "architecture_insights": {
                "top_critical_modules": [m.path for m in sorted(self.codebase.modules, key=lambda x: getattr(x, "pagerank", 0), reverse=True)[:5]],
                "entry_points": [m.path for m in self.codebase.modules if m.is_entry_point]
            },
            "risk_analysis": {
                "dead_code_candidates": [d.model_dump() for d in self.codebase.dead_code_candidates],
                "circular_dependencies": [c.model_dump() for c in self.codebase.circular_dependencies],
                "parse_errors": [e.model_dump() for e in self.codebase.analysis_errors]
            },
            "dataset_summary": [d.name for d in self.codebase.datasets]
        }
        (out_dir / "analysis_report.json").write_text(json.dumps(ar_data, indent=2), encoding="utf-8")
        
        logger.info(f"Saved independent analytical artifacts to {out_dir}")

    @classmethod
    def load(cls, filepath: Path) -> KnowledgeGraphWrapped:
        """Deserialize from JSON to full object graph (M-11)."""
        content = filepath.read_text(encoding="utf-8")
        data = json.loads(content)
        codebase = CodebaseGraph.model_validate(data)
        return cls(codebase)
