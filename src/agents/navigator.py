"""
Navigator Agent — Interactive Query Interface.

A LangGraph agent with four read-only tools for querying the codebase
knowledge graph. Supports both natural language and structured queries.

Tools:
  find_implementation(concept)  — Semantic search over purpose statements
  trace_lineage(dataset, direction) — Graph BFS over lineage DAG
  blast_radius(module_path)     — Downstream dependency graph
  explain_module(path)          — Generative explanation from code + context
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from src.agents.hydrologist import Hydrologist
from src.graph.knowledge_graph import KnowledgeGraphWrapped
from src.models.schemas import CodebaseGraph, ModuleNode, TransformationNode

logger = logging.getLogger(__name__)


# =============================================================================
# Navigator Evidence (Enhanced Schema)
# =============================================================================


class NavigatorEvidence:
    """Evidence citation for Navigator responses."""

    def __init__(
        self,
        file: str,
        line_range: Tuple[int, int] = (0, 0),
        analysis_method: str = "static_analysis",
        node_id: Optional[str] = None,
        confidence: float = 1.0,
    ):
        self.file = file
        self.line_range = line_range
        self.analysis_method = analysis_method
        self.node_id = node_id
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "line_range": self.line_range,
            "analysis_method": self.analysis_method,
            "node_id": self.node_id,
            "confidence": self.confidence,
        }

    def __repr__(self) -> str:
        return f"[{self.analysis_method}] {self.file}:{self.line_range[0]}-{self.line_range[1]}"


# =============================================================================
# Navigator Tool Implementations (Read-Only)
# =============================================================================


class NavigatorTools:
    """Read-only tool implementations for querying the knowledge graph.

    These tools NEVER modify any artifacts or files.
    """

    # Semantic search config
    EMBEDDING_MODEL = "all-MiniLM-L6-v2"
    SIMILARITY_METRIC = "cosine"
    TOP_K_RESULTS = 5
    MIN_SIMILARITY_THRESHOLD = 0.35

    def __init__(
        self,
        graph: CodebaseGraph,
        hydro: Hydrologist,
        repo_path: Optional[str] = None,
    ):
        self.graph = graph
        self.hydro = hydro
        self.repo_path = repo_path or graph.repo_path
        self._embeddings = None
        self._embedded_modules: List[ModuleNode] = []

    # ── Tool 1: find_implementation ─────────────────────────────────────

    def find_implementation(self, concept: str) -> str:
        """Semantic search over purpose statements to find where a concept is implemented.

        Uses sentence-transformers embeddings when available, falls back to
        keyword matching.

        Args:
            concept: Natural language description of what to find.

        Returns:
            Formatted response with top matches and evidence.
        """
        results = self._semantic_search(concept)

        if not results:
            return f"No modules found matching concept: '{concept}'"

        lines = [f"## Implementations matching: '{concept}'\n"]
        for i, (module, score) in enumerate(results, 1):
            ev = NavigatorEvidence(
                file=module.path,
                line_range=(1, module.lines_of_code),
                analysis_method="semantic_search" if self._embeddings is not None else "keyword_match",
                confidence=score,
            )
            purpose = module.purpose_statement or "No purpose statement available"
            lines.append(
                f"\n### {i}. `{module.path}` (similarity: {score:.2f})\n"
                f"**Domain:** {module.domain_cluster or 'uncategorized'}\n"
                f"**Purpose:** {purpose}\n"
                f"**Evidence:** {ev}\n"
            )
        return "\n".join(lines)

    def _semantic_search(self, query: str) -> List[tuple]:
        """Search modules by purpose statement similarity.

        Tries sentence-transformers first, falls back to keyword matching.
        """
        modules_with_purpose = [
            m for m in self.graph.modules if m.purpose_statement
        ]

        if not modules_with_purpose:
            return self._keyword_search(query)

        # Try embedding-based search
        try:
            if self._embeddings is None:
                self._build_embeddings(modules_with_purpose)

            if self._embeddings is not None:
                from sentence_transformers import SentenceTransformer

                model = SentenceTransformer(self.EMBEDDING_MODEL)
                query_emb = model.encode([query])

                from numpy import dot
                from numpy.linalg import norm

                results = []
                for i, mod in enumerate(self._embedded_modules):
                    sim = float(
                        dot(query_emb[0], self._embeddings[i])
                        / (norm(query_emb[0]) * norm(self._embeddings[i]) + 1e-8)
                    )
                    if sim >= self.MIN_SIMILARITY_THRESHOLD:
                        results.append((mod, sim))

                # Sort by similarity, then by PageRank for ties
                results.sort(key=lambda x: (-x[1], -x[0].pagerank))
                return results[: self.TOP_K_RESULTS]

        except ImportError:
            logger.info("sentence-transformers not available, using keyword fallback")
        except Exception as e:
            logger.warning(f"Embedding search failed ({e}), using keyword fallback")

        return self._keyword_search(query)

    def _build_embeddings(self, modules: List[ModuleNode]) -> None:
        """Build embeddings for all modules with purpose statements."""
        try:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(self.EMBEDDING_MODEL)
            texts = [m.purpose_statement or "" for m in modules]
            self._embeddings = model.encode(texts)
            self._embedded_modules = modules
            logger.info(f"Built embeddings for {len(modules)} modules")
        except ImportError:
            logger.info("sentence-transformers not installed, embeddings unavailable")
            self._embeddings = None

    def _keyword_search(self, query: str) -> List[tuple]:
        """Fallback keyword matching when embeddings are unavailable."""
        query_terms = set(query.lower().split())
        results = []
        for mod in self.graph.modules:
            text = f"{mod.path} {mod.purpose_statement or ''} {mod.domain_cluster or ''}".lower()
            matches = sum(1 for t in query_terms if t in text)
            if matches > 0:
                score = matches / len(query_terms)
                results.append((mod, score))

        results.sort(key=lambda x: (-x[1], -x[0].pagerank))
        return results[: self.TOP_K_RESULTS]

    # ── Tool 2: trace_lineage ───────────────────────────────────────────

    def trace_lineage(
        self,
        dataset: str,
        direction: str = "upstream",
    ) -> str:
        """Trace data lineage upstream or downstream from a dataset.

        Args:
            dataset: Name or ID of the dataset node.
            direction: 'upstream' (predecessors) or 'downstream' (successors).

        Returns:
            Formatted response with lineage path and evidence.
        """
        # Resolve dataset name to node ID
        node_id = self._resolve_node(dataset)
        if not node_id:
            return f"Dataset '{dataset}' not found in lineage graph. Available nodes include: {', '.join(list(self.hydro.graph.nodes())[:10])}"

        if direction == "upstream":
            deps = self.hydro.get_upstream_dependencies(node_id)
            label = "Upstream sources"
        else:
            deps = self.hydro.get_downstream_dependents(node_id)
            label = "Downstream dependents"

        if not deps:
            return f"No {direction} dependencies found for '{node_id}'."

        lines = [f"## {label} of `{node_id}`\n"]
        lines.append(f"**Total {direction} nodes:** {len(deps)}\n")

        for dep in sorted(deps):
            node_data = self.hydro.graph.nodes.get(dep, {})
            node_type = node_data.get("type", "unknown")
            source_file = node_data.get("source_file", "")
            ev = NavigatorEvidence(
                file=source_file or dep,
                analysis_method="graph_traversal",
                node_id=dep,
            )
            lines.append(f"- `{dep}` ({node_type}) — {ev}\n")

        return "\n".join(lines)

    def _resolve_node(self, name: str) -> Optional[str]:
        """Resolve a human-friendly name to a graph node ID."""
        # Direct match
        if name in self.hydro.graph:
            return name

        # Try common prefixes
        for prefix in ["dataset:", "transformation:", "dataset:file:"]:
            candidate = f"{prefix}{name}"
            if candidate in self.hydro.graph:
                return candidate

        # Fuzzy match on node names
        name_lower = name.lower()
        for node_id in self.hydro.graph.nodes():
            if name_lower in node_id.lower():
                return node_id

        return None

    # ── Tool 3: blast_radius ────────────────────────────────────────────

    def blast_radius(self, module_path: str) -> str:
        """Calculate blast radius for a module — what breaks if it changes.

        Maps module_path → TransformationNode via source_file, then uses
        Hydrologist.blast_radius() for graph traversal.

        Args:
            module_path: File path of the module to analyze.

        Returns:
            Formatted response with dependency graph and distances.
        """
        # Map module to transformation node via TransformationNode.source_file
        matching_node = None
        for t in self.graph.transformations:
            if t.source_file == module_path:
                matching_node = t.node_id
                break

        # Fallback: stem matching
        if not matching_node:
            stem = Path(module_path).stem
            for candidate in [f"transformation:{stem}", f"dataset:{stem}"]:
                if candidate in self.hydro.graph:
                    matching_node = candidate
                    break

        if not matching_node:
            return f"No lineage node found for module '{module_path}'. Cannot compute blast radius."

        radius = self.hydro.blast_radius(matching_node)
        if not radius:
            return f"Module `{module_path}` (node: `{matching_node}`) has no downstream dependents."

        lines = [f"## Blast Radius: `{module_path}`\n"]
        lines.append(f"**Lineage node:** `{matching_node}`\n")
        lines.append(f"**Total downstream impact:** {len(radius)} nodes\n\n")

        # Group by distance
        by_distance: Dict[int, List[str]] = {}
        for node, dist in sorted(radius.items(), key=lambda x: x[1]):
            by_distance.setdefault(dist, []).append(node)
            ev = NavigatorEvidence(
                file=module_path,
                analysis_method="graph_traversal",
                node_id=node,
            )

        for dist in sorted(by_distance.keys()):
            lines.append(f"### Distance {dist}\n")
            for node in by_distance[dist]:
                lines.append(f"- `{node}` *(graph_traversal)*\n")
            lines.append("\n")

        return "\n".join(lines)

    # ── Tool 4: explain_module ──────────────────────────────────────────

    def explain_module(self, path: str) -> str:
        """Generate a contextual explanation of a module.

        Combines purpose statement, domain cluster, imports, and code
        structure. Uses LLM when available, falls back to static data.

        Args:
            path: Relative path of the module within the repository.

        Returns:
            Formatted explanation with evidence citations.
        """
        # Find the module
        module = next((m for m in self.graph.modules if m.path == path), None)
        if not module:
            # Try partial match
            module = next(
                (m for m in self.graph.modules if path in m.path),
                None,
            )
        if not module:
            return f"Module '{path}' not found in the knowledge graph."

        lines = [f"## Module Explanation: `{module.path}`\n"]
        lines.append(f"**Language:** {module.language}\n")
        lines.append(f"**Domain:** {module.domain_cluster or 'uncategorized'}\n")
        lines.append(f"**Lines of Code:** {module.lines_of_code}\n")
        lines.append(f"**Complexity Score:** {module.complexity_score}\n")
        lines.append(f"**PageRank:** {module.pagerank:.4f}\n")

        if module.is_entry_point:
            lines.append(f"**Entry Point:** Yes ({module.entry_point_type})\n")
        if module.is_dead_code_candidate:
            lines.append("**⚠️ Flagged as dead code candidate**\n")
        if module.doc_drift:
            lines.append("**⚠️ Documentation drift detected**\n")

        lines.append(f"\n### Purpose\n\n")
        if module.purpose_statement:
            ev = NavigatorEvidence(
                file=module.path,
                line_range=(1, module.lines_of_code),
                analysis_method="llm_inference",
            )
            lines.append(f"{module.purpose_statement}\n\n*Evidence: {ev}*\n")
        else:
            lines.append("No purpose statement generated.\n")

        if module.imports:
            lines.append(f"\n### Dependencies ({len(module.imports)})\n\n")
            for imp in module.imports[:15]:
                lines.append(f"- `{imp}`\n")
            if len(module.imports) > 15:
                lines.append(f"- ... and {len(module.imports) - 15} more\n")

        if module.public_functions:
            lines.append(f"\n### Public API ({len(module.public_functions)})\n\n")
            for fn in module.public_functions:
                lines.append(f"- `{fn}`\n")

        # Try LLM explanation if available
        try:
            llm_explanation = self._llm_explain(module)
            if llm_explanation:
                lines.append(f"\n### AI Analysis\n\n{llm_explanation}\n")
                lines.append("*(analysis_method: llm_inference)*\n")
        except Exception:
            pass  # Static explanation is sufficient

        return "\n".join(lines)

    def _llm_explain(self, module: ModuleNode) -> Optional[str]:
        """Attempt to generate an LLM explanation. Returns None on failure."""
        try:
            import litellm

            # Read the code if possible
            code_path = Path(self.repo_path) / module.path
            if not code_path.exists():
                return None

            code = code_path.read_text(encoding="utf-8")[:4000]

            response = litellm.completion(
                model=os.getenv("CARTOGRAPHER_BULK_MODEL", "openrouter/google/gemini-flash-1.5"),
                messages=[
                    {
                        "role": "system",
                        "content": "You are a code analysis expert. Explain what this module does in 2-3 sentences, focusing on its business purpose, not implementation details.",
                    },
                    {
                        "role": "user",
                        "content": f"Module: {module.path}\nDomain: {module.domain_cluster}\nImports: {module.imports[:10]}\n\nCode:\n{code}",
                    },
                ],
                max_tokens=200,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.debug(f"LLM explain failed for {module.path}: {e}")
            return None


# =============================================================================
# Navigator REPL (Interactive Query Interface)
# =============================================================================


class NavigatorAgent:
    """Interactive query agent using LangGraph.

    Provides a REPL interface for querying the codebase knowledge graph
    with the four Navigator tools. Falls back to a simple tool-dispatch
    REPL if LangGraph is unavailable.
    """

    # Explicit query routing rules
    ROUTE_PATTERNS = {
        "trace_lineage": ["upstream", "downstream", "feeds", "produces", "consumes", "lineage", "sources", "where does"],
        "blast_radius": ["blast", "impact", "breaks", "what if", "radius", "change", "affect"],
        "explain_module": [".py", ".sql", ".yml", ".yaml", "explain", "/"],
        "find_implementation": ["where is", "find", "search", "implement", "logic", "calculation"],
    }

    def __init__(
        self,
        graph: CodebaseGraph,
        hydro: Hydrologist,
        repo_path: Optional[str] = None,
    ):
        self.tools = NavigatorTools(graph, hydro, repo_path)
        self.graph = graph

    def route_query(self, query: str) -> str:
        """Route a query to the appropriate tool based on pattern matching."""
        query_lower = query.lower().strip()

        # Score each tool by matching patterns
        scores: Dict[str, int] = {}
        for tool_name, patterns in self.ROUTE_PATTERNS.items():
            scores[tool_name] = sum(1 for p in patterns if p in query_lower)

        best_tool = max(scores, key=scores.get)  # type: ignore

        if scores[best_tool] == 0:
            # No patterns matched — default to find_implementation
            best_tool = "find_implementation"

        return self._execute_tool(best_tool, query)

    def _execute_tool(self, tool_name: str, query: str) -> str:
        """Execute a specific tool with the given query."""
        try:
            if tool_name == "find_implementation":
                return self.tools.find_implementation(query)
            elif tool_name == "trace_lineage":
                # Extract dataset name and direction
                direction = "upstream"
                if "downstream" in query.lower():
                    direction = "downstream"
                # Try to extract the dataset name
                dataset = self._extract_dataset_name(query)
                return self.tools.trace_lineage(dataset, direction)
            elif tool_name == "blast_radius":
                module_path = self._extract_module_path(query)
                return self.tools.blast_radius(module_path)
            elif tool_name == "explain_module":
                module_path = self._extract_module_path(query)
                return self.tools.explain_module(module_path)
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            return f"Error executing {tool_name}: {e}"

    def _extract_dataset_name(self, query: str) -> str:
        """Extract a dataset name from a natural language query."""
        # Look for quoted strings
        import re
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', query)
        if quoted:
            return quoted[0][0] or quoted[0][1]

        # Look for backtick-wrapped terms
        backtick = re.findall(r"`([^`]+)`", query)
        if backtick:
            return backtick[0]

        # Look for words that look like table/dataset names
        words = query.split()
        for w in words:
            if "_" in w or "." in w:
                return w.strip("?.,!")

        # Return the last meaningful word
        stop_words = {"what", "where", "the", "is", "are", "does", "do", "from", "to", "of", "feeds", "upstream", "downstream", "sources"}
        meaningful = [w for w in words if w.lower() not in stop_words]
        return meaningful[-1] if meaningful else query

    def _extract_module_path(self, query: str) -> str:
        """Extract a file path from a natural language query."""
        import re

        # Look for file paths
        paths = re.findall(r"[\w/\\.-]+\.(?:py|sql|yml|yaml)", query)
        if paths:
            return paths[0]

        # Look for quoted strings
        quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', query)
        if quoted:
            return quoted[0][0] or quoted[0][1]

        # Look for backtick-wrapped terms
        backtick = re.findall(r"`([^`]+)`", query)
        if backtick:
            return backtick[0]

        # Return cleaned query
        stop_words = {"what", "explain", "blast", "radius", "breaks", "if", "i", "change", "module"}
        words = [w for w in query.split() if w.lower() not in stop_words]
        return " ".join(words).strip()

    def run_repl(self) -> None:
        """Run interactive Navigator REPL.

        Reads user queries and routes them to the appropriate tool.
        Type 'help' for available commands or 'exit' to quit.
        """
        print("\n" + "=" * 68)
        print("  THE BROWNFIELD CARTOGRAPHER — Navigator Query Interface")
        print("=" * 68)
        print(f"\n  Knowledge graph loaded: {len(self.graph.modules)} modules")
        print(f"  Lineage graph: {self.tools.hydro.graph.number_of_nodes()} nodes")
        print(f"\n  Commands:")
        print(f"    find <concept>              — Semantic search for implementations")
        print(f"    lineage <dataset> [up|down]  — Trace data lineage")
        print(f"    blast <module_path>          — Calculate blast radius")
        print(f"    explain <module_path>        — Explain a module")
        print(f"    help                         — Show this help")
        print(f"    exit                         — Quit")
        print("=" * 68 + "\n")

        while True:
            try:
                query = input("navigator> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye!")
                break

            if not query:
                continue
            if query.lower() in ("exit", "quit", "q"):
                print("Goodbye!")
                break
            if query.lower() == "help":
                self._print_help()
                continue

            # Route and execute
            result = self.route_query(query)
            print(f"\n{result}\n")

    def _print_help(self) -> None:
        print("\nAvailable tools:")
        print("  find_implementation  — 'Where is the revenue calculation logic?'")
        print("  trace_lineage       — 'What produces the daily_active_users table?'")
        print("  blast_radius        — 'What breaks if I change src/transforms/revenue.py?'")
        print("  explain_module      — 'Explain what src/ingestion/kafka_consumer.py does'")
        print("\nTips:")
        print("  - Wrap dataset or module names in quotes or backticks")
        print("  - Use 'upstream' or 'downstream' for lineage direction")
        print("  - All queries are read-only and do not modify artifacts\n")


# =============================================================================
# LangGraph Integration (Optional — uses simple REPL as fallback)
# =============================================================================


def build_langgraph_navigator(
    graph: CodebaseGraph,
    hydro: Hydrologist,
    repo_path: Optional[str] = None,
):
    """Build a LangGraph StateGraph agent with the 4 Navigator tools.

    Returns the compiled graph, or None if LangGraph is not available.
    """
    try:
        from typing import Annotated, TypedDict
        from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
        from langchain_core.tools import tool
        from langgraph.graph import StateGraph, START, END
        from langgraph.graph.message import add_messages

        tools_impl = NavigatorTools(graph, hydro, repo_path)

        # Define tools as langchain tool functions
        @tool
        def find_implementation(concept: str) -> str:
            """Search for where a concept is implemented in the codebase."""
            return tools_impl.find_implementation(concept)

        @tool
        def trace_lineage(dataset: str, direction: str = "upstream") -> str:
            """Trace data lineage upstream or downstream from a dataset."""
            return tools_impl.trace_lineage(dataset, direction)

        @tool
        def blast_radius(module_path: str) -> str:
            """Calculate what would break if a module changes."""
            return tools_impl.blast_radius(module_path)

        @tool
        def explain_module(path: str) -> str:
            """Explain what a specific module does with evidence citations."""
            return tools_impl.explain_module(path)

        tool_registry = {
            "find_implementation": find_implementation,
            "trace_lineage": trace_lineage,
            "blast_radius": blast_radius,
            "explain_module": explain_module,
        }

        class NavigatorState(TypedDict):
            messages: Annotated[list, add_messages]

        def agent_node(state: NavigatorState) -> NavigatorState:
            """Process user message and decide which tool to call."""
            last_msg = state["messages"][-1]
            if isinstance(last_msg, HumanMessage):
                query = last_msg.content
                # Simple routing
                nav = NavigatorAgent(graph, hydro, repo_path)
                result = nav.route_query(query)
                return {"messages": [AIMessage(content=result)]}
            return state

        builder = StateGraph(NavigatorState)
        builder.add_node("agent", agent_node)
        builder.add_edge(START, "agent")
        builder.add_edge("agent", END)

        return builder.compile()

    except ImportError as e:
        logger.warning(f"LangGraph not available: {e}. Using simple REPL fallback.")
        return None
