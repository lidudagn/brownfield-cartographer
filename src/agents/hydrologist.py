"""
Hydrologist Agent — Data Flow & Lineage Analyst.

Constructs the DataLineageGraph by analyzing data sources, transformations,
and sinks across Python, SQL, and YAML. Provides graph reasoning:
blast_radius, source/sink identification, cycle detection, and path tracing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple, Any

import networkx as nx

from src.models.schemas import (
    CodebaseGraph,
    ConsumesEdge,
    DatasetNode,
    Evidence,
    ModuleNode,
    ProducesEdge,
    TransformationNode,
)

logger = logging.getLogger(__name__)


class Hydrologist:
    """Agent responsible for building and querying the data lineage graph.

    The Hydrologist takes the CodebaseGraph produced by the Surveyor and
    constructs a DataLineageGraph (NetworkX DiGraph) where:
    - Nodes are datasets (tables/files/streams) and transformations
    - Edges represent data flow: CONSUMES (dataset → transformation)
      and PRODUCES (transformation → dataset)

    This graph answers:
    - 'What upstream sources feed this output dataset?'
    - 'What would break if I change the schema of table Y?'
    - 'What are the entry/exit points of the data system?'
    """

    def __init__(self) -> None:
        self.graph = nx.DiGraph()
        self._sources: List[str] = []
        self._sinks: List[str] = []

    # =========================================================================
    # Graph Construction
    # =========================================================================

    def build_lineage_graph(self, codebase_graph: CodebaseGraph) -> nx.DiGraph:
        """Build the in-memory NetworkX DiGraph from CodebaseGraph.

        Merges SQL lineage (from Surveyor's sqlglot extraction), Python data
        flows (datasets_read/datasets_written), and YAML config topology into
        a unified DAG.
        """
        self.graph.clear()

        # 1. Add Dataset Nodes
        for d in codebase_graph.datasets:
            self.graph.add_node(
                d.node_id,
                type="dataset",
                name=d.name,
                storage_type=d.storage_type,
                data=d,
            )

        # 2. Add Transformation Nodes
        for t in codebase_graph.transformations:
            self.graph.add_node(
                t.node_id,
                type="transformation",
                name=t.name,
                source_file=t.source_file,
                data=t,
            )

        # 3. Wire CONSUMES edges (Dataset → Transformation)
        for e in codebase_graph.consumes_edges:
            if e.target not in self.graph:
                self.graph.add_node(
                    e.target,
                    type="dataset",
                    name=e.target.replace("dataset:", ""),
                    storage_type="table",
                )
                logger.debug("Added implicit dataset node: %s", e.target)
            self.graph.add_edge(
                e.target, e.source,
                type="consumes",
                evidence=e.evidence,
            )

        # 4. Wire PRODUCES edges (Transformation → Dataset)
        for e in codebase_graph.produces_edges:
            if e.target not in self.graph:
                self.graph.add_node(
                    e.target,
                    type="dataset",
                    name=e.target.replace("dataset:", ""),
                    storage_type="table",
                )
                logger.debug("Added implicit dataset node: %s", e.target)
            self.graph.add_edge(
                e.source, e.target,
                type="produces",
                evidence=e.evidence,
            )

        # 5. Wire Python data flows (pandas/PySpark reads/writes)
        self._wire_python_data_flows(codebase_graph.modules)

        # Cache sources and sinks
        self._sources = [n for n in self.graph.nodes() if self.graph.in_degree(n) == 0]
        self._sinks = [n for n in self.graph.nodes() if self.graph.out_degree(n) == 0]

        logger.info(
            "Lineage graph built: %d nodes, %d edges, %d sources, %d sinks",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
            len(self._sources),
            len(self._sinks),
        )

        return self.graph

    def _wire_python_data_flows(self, modules: List[ModuleNode]) -> None:
        """Integrate Python data flow reads/writes into the lineage graph.

        For each Python module with datasets_read or datasets_written,
        create implicit transformation and dataset nodes and wire them in.
        """
        for mod in modules:
            if mod.language != "python":
                continue

            if not mod.datasets_read and not mod.datasets_written:
                continue

            # Create a transformation node for this Python module
            t_id = f"transformation:py:{Path(mod.path).stem}"
            if t_id not in self.graph:
                self.graph.add_node(
                    t_id,
                    type="transformation",
                    name=Path(mod.path).stem,
                    source_file=mod.path,
                )

            # Wire reads as CONSUMES (dataset → transformation)
            for ds_path in mod.datasets_read:
                ds_id = f"dataset:file:{Path(ds_path).name}"
                if ds_id not in self.graph:
                    self.graph.add_node(
                        ds_id,
                        type="dataset",
                        name=Path(ds_path).name,
                        storage_type="file",
                    )
                self.graph.add_edge(ds_id, t_id, type="consumes")

            # Wire writes as PRODUCES (transformation → dataset)
            for ds_path in mod.datasets_written:
                ds_id = f"dataset:file:{Path(ds_path).name}"
                if ds_id not in self.graph:
                    self.graph.add_node(
                        ds_id,
                        type="dataset",
                        name=Path(ds_path).name,
                        storage_type="file",
                    )
                self.graph.add_edge(t_id, ds_id, type="produces")

    # =========================================================================
    # Graph Querying
    # =========================================================================

    def blast_radius(
        self,
        node_id: str,
        direction: Literal["downstream", "upstream", "both"] = "downstream",
    ) -> Dict[str, int]:
        """Calculate blast radius with shortest-path distances.

        Returns a dict mapping each affected node to its distance from the
        source node. Distance represents how many hops away the impact reaches.
        """
        if node_id not in self.graph:
            return {}

        result: Dict[str, int] = {}

        if direction in ("downstream", "both"):
            try:
                lengths = nx.single_source_shortest_path_length(self.graph, node_id)
                for n, dist in lengths.items():
                    if n != node_id:
                        result[n] = dist
            except nx.NetworkXError:
                pass

        if direction in ("upstream", "both"):
            try:
                rev = self.graph.reverse()
                lengths = nx.single_source_shortest_path_length(rev, node_id)
                for n, dist in lengths.items():
                    if n != node_id:
                        # Keep the minimum distance if already present
                        if n not in result or dist < result[n]:
                            result[n] = dist
            except nx.NetworkXError:
                pass

        return result

    def detect_cycles(self) -> List[List[str]]:
        """Detect cycles in the lineage DAG using nx.simple_cycles.

        A well-formed data pipeline should be a DAG. Cycles indicate
        circular dependencies that may cause infinite loops or stale data.
        """
        return list(nx.simple_cycles(self.graph))

    def trace_lineage(self, start_node: str, end_node: str) -> List[List[str]]:
        """Return all simple paths between two nodes in the lineage graph.

        Useful for answering: 'How does data flow from source A to output B?'
        """
        if start_node not in self.graph or end_node not in self.graph:
            return []
        try:
            return list(nx.all_simple_paths(self.graph, start_node, end_node))
        except nx.NodeNotFound:
            return []

    def get_statistics(self) -> Dict[str, Any]:
        """Get high-level graph statistics for reporting."""
        num_datasets = sum(
            1 for _, d in self.graph.nodes(data=True)
            if d.get("type") == "dataset"
        )
        num_transformations = sum(
            1 for _, d in self.graph.nodes(data=True)
            if d.get("type") == "transformation"
        )

        # Calculate max depth using DAG longest path if it is a DAG
        try:
            max_depth = len(nx.dag_longest_path(self.graph)) - 1
        except nx.NetworkXUnfeasible:
            max_depth = -1

        return {
            "num_nodes": self.graph.number_of_nodes(),
            "num_datasets": num_datasets,
            "num_transformations": num_transformations,
            "num_edges": self.graph.number_of_edges(),
            "num_sources": len(self._sources),
            "num_sinks": len(self._sinks),
            "max_lineage_depth": max_depth if max_depth >= 0 else "Has Cycles",
        }

    def find_sources(self) -> List[str]:
        """Find data source nodes (in-degree=0) — entry points of the data system."""
        return self._sources if self._sources else [
            n for n in self.graph.nodes() if self.graph.in_degree(n) == 0
        ]

    def find_sinks(self) -> List[str]:
        """Find data sink nodes (out-degree=0) — final outputs of the data system."""
        return self._sinks if self._sinks else [
            n for n in self.graph.nodes() if self.graph.out_degree(n) == 0
        ]

    def get_upstream_dependencies(self, node_id: str) -> List[str]:
        """Return all upstream ancestors of a node (all data that feeds into it)."""
        if node_id not in self.graph:
            return []
        return list(nx.ancestors(self.graph, node_id))

    def get_downstream_dependents(self, node_id: str) -> List[str]:
        """Return all downstream descendants of a node (all data affected by it)."""
        if node_id not in self.graph:
            return []
        return list(nx.descendants(self.graph, node_id))
