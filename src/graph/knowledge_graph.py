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

    @classmethod
    def load(cls, filepath: Path) -> KnowledgeGraphWrapped:
        """Deserialize from JSON to full object graph (M-11)."""
        content = filepath.read_text(encoding="utf-8")
        data = json.loads(content)
        codebase = CodebaseGraph.model_validate(data)
        return cls(codebase)
