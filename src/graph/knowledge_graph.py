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


def visualize_interactive_graph(graph: nx.DiGraph, output_path: Path) -> None:
    """Generate an interactive HTML visualization using pyvis."""
    try:
        from pyvis.network import Network
    except ImportError:
        logger.warning("pyvis not installed; skipping interactive visualization")
        return

    # Create network
    net = Network(height="1000px", width="100%", bgcolor="#222222", font_color="white", directed=True)
    
    # Hierarchical layout for directed flow (like a DAG)
    net.set_options("""
    var options = {
      "layout": {
        "hierarchical": {
          "enabled": true,
          "direction": "LR",
          "sortMethod": "directed",
          "nodeSpacing": 150,
          "levelSeparation": 250
        }
      },
      "physics": {
        "hierarchicalRepulsion": {
          "centralGravity": 0.0,
          "springLength": 100,
          "springConstant": 0.01,
          "nodeDistance": 150,
          "damping": 0.09
        },
        "solver": "hierarchicalRepulsion"
      }
    }
    """)
    
    # Calculate sizes and colors similar to matplotlib version
    try:
        pr = nx.pagerank(graph)
    except Exception:
        pr = {n: 0.1 for n in graph.nodes()}
        
    velocities = {}
    for n in graph.nodes():
        node_attr = graph.nodes[n].get("node")
        if node_attr and hasattr(node_attr, "change_velocity_30d"):
            velocities[n] = node_attr.change_velocity_30d
        else:
            velocities[n] = 0.0
            
    # Filters
    ignore_patterns = ["package-lock", "package.json", "taskfile", "poetry.lock", "makefile", "dockerfile", "dbt_project", ".gitignore", "generate_schema_name"]
    valid_nodes = set()
    
    for n in graph.nodes():
        path_str = str(n).lower()
        if any(pat in path_str for pat in ignore_patterns):
            continue
        valid_nodes.add(n)
        
    # Add nodes
    for n in valid_nodes:
        # Size based on pagerank
        size = 15 + pr.get(n, 0) * 80
        
        path_str = str(n).lower()
        
        # Color based on domain/type
        if "source" in path_str or "raw" in path_str or "seed" in path_str:
            color = "#2ca02c" # green
            group = "sources"
        elif "staging" in path_str or "stg_" in path_str:
            color = "#1f77b4" # blue
            group = "staging"
        elif "marts" in path_str or "core" in path_str:
            color = "#ff7f0e" # orange
            group = "marts"
        elif "macro" in path_str:
            color = "#9467bd" # purple
            group = "macros"
        else:
            color = "#7f7f7f" # gray
            group = "other"
            
        # Highlight high pagerank hubs
        if pr.get(n, 0) > 0.05:
            color = "#d62728" # red (high impact)
        
        label = Path(str(n)).stem
        title = f"Module: {n}\nPageRank: {pr.get(n, 0):.4f}\nVelocity: {velocities.get(n, 0):.2f}\nGroup: {group}"
        
        # Add node
        net.add_node(n, label=label, title=title, size=size, color=color, group=group)

    # Add edges
    for u, v, data in graph.edges(data=True):
        if u in valid_nodes and v in valid_nodes:
            # Drop self-loops from the vis to keep hierarchical clean
            if u != v:
                weight = data.get("weight", 1)
                net.add_edge(u, v, value=weight, title=f"Weight: {weight}")

    # Save to file
    try:
        net.write_html(str(output_path))
        logger.info(f"Generated interactive visualization at {output_path}")
    except Exception as e:
        logger.warning(f"Failed to generate interactive visualization: {e}")


def visualize_interactive_lineage(lineage_graph: nx.DiGraph, output_path: Path) -> None:
    """Generate an interactive HTML visualization for the pure Data Lineage DAG."""
    try:
        from pyvis.network import Network
    except ImportError:
        logger.warning("pyvis not installed; skipping interactive lineage visualization")
        return

    net = Network(height="1000px", width="100%", bgcolor="#222222", font_color="white", directed=True)
    
    # Hierarchical layout strictly for DAG
    net.set_options("""
    var options = {
      "layout": {
        "hierarchical": {
          "enabled": true,
          "direction": "UD",
          "sortMethod": "directed",
          "nodeSpacing": 200,
          "levelSeparation": 150
        }
      },
      "physics": {
        "hierarchicalRepulsion": {
          "centralGravity": 0.0,
          "springLength": 100,
          "springConstant": 0.01,
          "nodeDistance": 150,
          "damping": 0.09
        },
        "solver": "hierarchicalRepulsion"
      }
    }
    """)
    
    for n, data in lineage_graph.nodes(data=True):
        node_type = data.get("type", "unknown")
        
        # Base node styling
        size = 20
        label = data.get("name", str(n).replace("dataset:", "").replace("transformation:", ""))
        title = f"ID: {n}\nType: {node_type}"
        
        # Color coding & Shapes based on FDE feedback
        if node_type == "dataset":
            storage = data.get("storage_type", "")
            if "raw" in label or "source" in label:
                color = "#2ca02c"  # green (raw sources)
                group = "source"
            else:
                color = "#ff7f0e"  # orange (marts/datasets)
                group = "dataset"
            shape = "database"
            title += f"\nStorage: {storage}"
        elif node_type == "transformation":
            if "stg_" in label or "staging" in label:
                color = "#1f77b4"  # blue (staging models)
                group = "staging"
            else:
                color = "#9467bd"  # purple (other transforms)
                group = "transformation"
            shape = "box"
            title += f"\nFile: {data.get('source_file', '')}"
        else:
            color = "#7f7f7f"
            shape = "ellipse"
            group = "other"

        net.add_node(n, label=label, title=title, size=size, color=color, shape=shape, group=group)

    for u, v, data in lineage_graph.edges(data=True):
        if u != v:
            edge_type = data.get("type", "")
            title = f"Type: {edge_type}"
            color = "#666666" if edge_type == "consumes" else "#aaaaaa"
            net.add_edge(u, v, title=title, color=color)

    try:
        net.write_html(str(output_path))
        logger.info(f"Generated interactive LINEAGE visualization at {output_path}")
    except Exception as e:
        logger.warning(f"Failed to generate interactive LINEAGE visualization: {e}")





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
        
        # Generate interactive HTML graph alongside the PNG
        html_path = output_path.with_suffix(".html")
        visualize_interactive_graph(self.nx_graph, html_path)

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
        
        # 0. module_graph.json (full CodebaseGraph — required deliverable)
        self.save(out_dir / "module_graph.json")
        
        # 1. modules.json
        md_data = {
            "repo_path": self.codebase.repo_path,
            "analysis_timestamp": self.codebase.analysis_timestamp,
            "modules": [m.model_dump() for m in self.codebase.modules],
            "functions": [f.model_dump() for f in self.codebase.functions]
        }
        (out_dir / "modules.json").write_text(json.dumps(md_data, indent=2), encoding="utf-8")
        
        # 2. transformations.json
        tr_data = {
            "transformations": [t.model_dump() for t in self.codebase.transformations]
        }
        (out_dir / "transformations.json").write_text(json.dumps(tr_data, indent=2), encoding="utf-8")
        
        # 3. datasets.json
        ds_data = {
            "datasets": [d.model_dump() for d in self.codebase.datasets]
        }
        (out_dir / "datasets.json").write_text(json.dumps(ds_data, indent=2), encoding="utf-8")

        # 4. edges.json
        ed_data = {
            "imports_edges": [e.model_dump() for e in self.codebase.imports_edges],
            "calls_edges": [e.model_dump() for e in self.codebase.calls_edges],
            "produces_edges": [e.model_dump() for e in self.codebase.produces_edges],
            "consumes_edges": [e.model_dump() for e in self.codebase.consumes_edges],
            "configures_edges": [e.model_dump() for e in getattr(self.codebase, "configures_edges", [])]
        }
        (out_dir / "edges.json").write_text(json.dumps(ed_data, indent=2), encoding="utf-8")
        
        # 5. lineage_graph.json (required deliverable — transformations + lineage edges)
        lineage_data = {
            "transformations": [t.model_dump() for t in self.codebase.transformations],
            "datasets": [d.model_dump() for d in self.codebase.datasets],
            "produces_edges": [e.model_dump() for e in self.codebase.produces_edges],
            "consumes_edges": [e.model_dump() for e in self.codebase.consumes_edges],
        }
        (out_dir / "lineage_graph.json").write_text(json.dumps(lineage_data, indent=2), encoding="utf-8")
        
        # 6. analysis_report.json
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
