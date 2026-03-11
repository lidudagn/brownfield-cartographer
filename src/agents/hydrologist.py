import networkx as nx
from typing import Dict, List, Literal, Optional, Tuple, Any

from src.models.schemas import CodebaseGraph

class Hydrologist:
    """Agent responsible for graph reasoning and lineage analysis."""

    def __init__(self):
        self.graph = nx.DiGraph()

    def build_lineage_graph(self, codebase_graph: CodebaseGraph) -> nx.DiGraph:
        """Build the in-memory NetworkX DiGraph directly from CodebaseGraph."""
        self.graph.clear()
        
        # Add Dataset Nodes
        for d in codebase_graph.datasets:
            self.graph.add_node(d.node_id, type="dataset", name=d.name, data=d)
            
        # Add Transformation Nodes
        for t in codebase_graph.transformations:
            self.graph.add_node(t.node_id, type="transformation", name=t.name, data=t)
            
        # Add Consumes Edges (Dataset -> Transformation)
        for e in codebase_graph.consumes_edges:
            # consumes means transformation consumes dataset: Dataset -> Transformation
            # Ensure target dataset exists (it should, but safety first)
            if e.target not in self.graph:
                # Add a dummy node if it wasn't statically parsed
                self.graph.add_node(e.target, type="dataset", name=e.target.replace("dataset:", ""))
            self.graph.add_edge(e.target, e.source, type="consumes", evidence=e.evidence)
            
        # Add Produces Edges (Transformation -> Dataset)
        for e in codebase_graph.produces_edges:
            # produces means transformation produces dataset: Transformation -> Dataset
            if e.target not in self.graph:
                self.graph.add_node(e.target, type="dataset", name=e.target.replace("dataset:", ""))
            self.graph.add_edge(e.source, e.target, type="produces", evidence=e.evidence)
            
        return self.graph

    def blast_radius(self, node_id: str, direction: Literal["downstream", "upstream", "both"] = "downstream") -> Dict[str, int]:
        """Calculate blast radius using shortest paths."""
        if node_id not in self.graph:
            return {}
            
        result = {}
        
        if direction in ("downstream", "both"):
            lengths = nx.single_source_shortest_path_length(self.graph, node_id)
            for n, d in lengths.items():
                if n != node_id and (n not in result or d < result[n]):
                    result[n] = d
                    
        if direction in ("upstream", "both"):
            reversed_graph = self.graph.reverse(copy=False)
            lengths = nx.single_source_shortest_path_length(reversed_graph, node_id)
            for n, d in lengths.items():
                if n != node_id and (n not in result or d < result[n]):
                    result[n] = d
                    
        return result

    def detect_cycles(self) -> List[List[str]]:
        """Detect cycles utilizing nx.simple_cycles."""
        # simple_cycles returns a generator of lists of cycle nodes.
        return list(nx.simple_cycles(self.graph))

    def trace_lineage(self, start_node: str, end_node: str) -> List[List[str]]:
        """Return all simple paths between two nodes."""
        if start_node not in self.graph or end_node not in self.graph:
            return []
        # Return all paths
        return list(nx.all_simple_paths(self.graph, start_node, end_node))

    def get_statistics(self) -> Dict[str, Any]:
        """Get high-level graph statistics."""
        num_datasets = sum(1 for _, d in self.graph.nodes(data=True) if d.get("type") == "dataset")
        num_transformations = sum(1 for _, d in self.graph.nodes(data=True) if d.get("type") == "transformation")
        
        # Calculate max depth using DAG longest path if it is a DAG
        try:
            max_depth = len(nx.dag_longest_path(self.graph)) - 1
        except nx.NetworkXUnfeasible:
            # Graph has cycles, fallback to simple estimate or 0
            max_depth = -1
            
        return {
            "num_nodes": self.graph.number_of_nodes(),
            "num_datasets": num_datasets,
            "num_transformations": num_transformations,
            "num_edges": self.graph.number_of_edges(),
            "max_lineage_depth": max_depth if max_depth >= 0 else "Has Cycles"
        }

    def find_sources(self) -> List[str]:
        """Find data source nodes (in-degree=0) — entry points of the data system."""
        return [n for n in self.graph.nodes() if self.graph.in_degree(n) == 0]

    def find_sinks(self) -> List[str]:
        """Find data sink nodes (out-degree=0) — final outputs of the data system."""
        return [n for n in self.graph.nodes() if self.graph.out_degree(n) == 0]
