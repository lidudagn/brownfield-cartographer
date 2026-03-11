"""
Pydantic schemas for The Brownfield Cartographer knowledge graph.

All node types, edge types, error hierarchy, evidence model, column-level lineage,
dead code candidate scoring, circular dependency reporting, and dbt config validation.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


# =============================================================================
# Evidence Model (C-3, MF-2)
# =============================================================================


class Evidence(BaseModel):
    """Traceable proof linking an analysis result to its source code location.

    Every edge and analysis finding includes Evidence so that users can verify
    the Cartographer's output against the actual codebase.
    """

    file_path: str
    line_start: int  # 1-indexed
    line_end: int
    column_start: int = 0
    column_end: int = 0
    snippet: str  # Actual code text at this location
    analysis_method: Literal[
        "tree_sitter", "sqlglot", "regex", "git", "yaml_parse"
    ]

    @model_validator(mode="after")
    def validate_line_range(self) -> "Evidence":
        if self.line_start > self.line_end:
            raise ValueError(f"line_start ({self.line_start}) cannot be greater than line_end ({self.line_end})")
        return self

    def verify(self, repo_root: str) -> bool:
        """Verify evidence exists at claimed location in the actual file."""
        full_path = Path(repo_root) / self.file_path
        if not full_path.exists():
            return False
        try:
            lines = full_path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            return False
        if self.line_start < 1 or self.line_start > len(lines):
            return False
        actual = "\n".join(lines[self.line_start - 1 : self.line_end])
        return self.snippet.strip() in actual


# =============================================================================
# Error Hierarchy (F-2, R-4, R-5)
# =============================================================================


class AnalysisError(BaseModel):
    """Typed error classification for graceful degradation.

    Different error types trigger different recovery strategies:
    - parse_error: Syntax issue, fallback to minimal placeholder node
    - partial_parse: Some structures extracted, others failed
    - unrecoverable: File cannot be processed at all, skip entirely
    """

    error_type: Literal["parse_error", "partial_parse", "unrecoverable"]
    file_path: str
    message: str
    recoverable: bool
    fallback_used: Literal["minimal_placeholder", "partial_results", "skipped"]


# =============================================================================
# Column-Level Lineage (F-5, MF-1)
# =============================================================================


class ColumnLineage(BaseModel):
    """Tracks how a single output column is derived from source columns.

    Enables answering: 'Why does this metric look wrong today?' by tracing
    column provenance through CTE chains and transformations.
    """

    target_column: str
    source_columns: List[str]  # ["stg_orders.order_id", "stg_orders.subtotal"]
    transformation: Literal[
        "passthrough", "rename", "aggregate", "compute", "case", "window", "cast", "wildcard_passthrough"
    ]
    expression: Optional[str] = None  # e.g., "sum(subtotal)"
    source_file: str = ""
    line_range: Tuple[int, int] = (0, 0)


# =============================================================================
# Node Types
# =============================================================================


class ModuleNode(BaseModel):
    """Represents a single file in the codebase with all static analysis metadata.

    This is the primary unit of analysis — every file in the repo becomes one
    ModuleNode, whether fully parsed or a minimal placeholder.
    """

    model_config = ConfigDict(extra="forbid")

    path: str  # Relative to repo root
    node_type: Literal["module"] = "module"
    language: Literal[
        "python", "sql", "yaml", "jinja_sql", "csv", "unknown"
    ]
    purpose_statement: Optional[str] = None
    domain_cluster: Optional[str] = None
    complexity_score: int = Field(
        default=1,
        description="Cyclomatic complexity: decision_points + 1",
    )
    change_velocity_30d: float = Field(
        default=0.0,
        description="unique_change_days / 30",
    )
    pagerank: float = 0.0
    is_dead_code_candidate: bool = False
    is_entry_point: bool = False
    entry_point_type: Optional[
        Literal["seed", "mart", "exposure", "cli", "dag", "test"]
    ] = None
    last_modified: Optional[str] = None
    imports: List[str] = Field(
        default_factory=list, description="Module paths this file depends on"
    )
    public_functions: List[str] = Field(default_factory=list)
    called_macros: List[str] = Field(default_factory=list)
    classes: List[str] = Field(default_factory=list)
    cte_definitions: List[str] = Field(default_factory=list)
    datasets_read: List[str] = Field(default_factory=list)
    datasets_written: List[str] = Field(default_factory=list)
    dag_metadata: Dict[str, Any] = Field(default_factory=dict)
    doc_drift: bool = Field(
        default=False,
        description="True if the implementation contradicts the docstring.",
    )
    lines_of_code: int = 0
    comment_ratio: float = Field(
        default=0.0,
        description="comment_lines / total_lines (line-based, NOT node-based)",
    )
    is_complete_parse: bool = Field(
        default=True,
        description="False if only partially parsed due to errors",
    )
    parse_errors: List[AnalysisError] = Field(default_factory=list)


class DatasetNode(BaseModel):
    """Represents a data source or sink in the system — a table, file, stream, or API.

    In dbt codebases, these are the source() tables and seed CSVs. Schema snapshots
    capture column definitions for downstream drift detection.
    """

    node_id: str
    name: str
    node_type: Literal["dataset"] = "dataset"
    storage_type: Literal["table", "file", "stream", "api", "seed"]
    schema_snapshot: Dict[str, str] = Field(
        default_factory=dict,
        description="column_name → data_type mapping from YAML/SQL",
    )
    freshness_sla: Optional[str] = Field(
        default=None, description="From dbt loaded_at_field"
    )
    owner: Optional[str] = Field(
        default=None, description="From dbt meta.owner"
    )
    is_source_of_truth: bool = False
    source_file: Optional[str] = None


class FunctionNode(BaseModel):
    """Represents a single function or method extracted from a Python module."""

    qualified_name: str
    parent_module: str
    signature: str
    purpose_statement: Optional[str] = None
    call_count_within_repo: int = 0
    is_public_api: bool = True


class TransformationNode(BaseModel):
    """Represents a data transformation that converts source datasets to targets.

    In dbt, each SQL model is a TransformationNode. The column_lineage field
    tracks column-level provenance through the transformation.
    """

    node_id: str
    name: str
    node_type: Literal["transformation"] = "transformation"
    source_datasets: List[str]
    target_datasets: List[str]
    transformation_type: Literal[
        "select", "aggregate", "join", "filter", "window", "cte", "macro"
    ]
    source_file: str
    line_range: Tuple[int, int]
    sql_query_if_applicable: Optional[str] = None
    column_lineage: List[ColumnLineage] = Field(default_factory=list)


# =============================================================================
# Edge Types — All carry Evidence (C-3, MF-2)
# =============================================================================


class EdgeBase(BaseModel):
    """Base edge type. All edges carry Evidence to link back to source code."""

    source: str
    target: str
    evidence: Evidence


class ImportsEdge(EdgeBase):
    """Module A imports Module B."""

    edge_type: Literal["IMPORTS"] = "IMPORTS"
    weight: int = 1
    is_dynamic: bool = Field(
        default=False, description="True for __import__() / importlib"
    )


class ProducesEdge(EdgeBase):
    """Transformation produces Dataset."""

    edge_type: Literal["PRODUCES"] = "PRODUCES"


class ConsumesEdge(EdgeBase):
    """Transformation consumes Dataset."""

    edge_type: Literal["CONSUMES"] = "CONSUMES"


class CallsEdge(EdgeBase):
    """Function A calls Function B."""

    edge_type: Literal["CALLS"] = "CALLS"


class ConfiguresEdge(EdgeBase):
    """Config file configures a module/pipeline."""

    edge_type: Literal["CONFIGURES"] = "CONFIGURES"


# Type alias for all edge types
AnyEdge = Union[ImportsEdge, ProducesEdge, ConsumesEdge, CallsEdge, ConfiguresEdge]


# =============================================================================
# Analysis Result Types
# =============================================================================


class UnresolvedReference(BaseModel):
    """A dependency that could not be statically resolved.

    Covers: dynamic Python imports, Jinja macro-wrapped ref() calls,
    and variable-based table references.
    """

    ref_type: Literal["dynamic_import", "macro_ref", "variable_ref"]
    raw_text: str
    source_file: str
    source_line: int
    reason: str


class DeadCodeCandidate(BaseModel):
    """A module flagged as potentially dead with confidence scoring (MF-3).

    4-factor scoring:
    - 0.4: No imports (in_degree=0)
    - 0.3: Last modified > 90 days / no recent velocity
    - 0.2: No tests referencing it
    - 0.1: Not in any dbt exposure
    """

    module_path: str
    in_degree: int  # should be 0
    is_entry_point: bool
    entry_point_type: Optional[str] = None
    explanation: str  # Human-readable WHY
    confidence: float = Field(ge=0.0, le=1.0)
    factors: Dict[str, bool] = Field(
        default_factory=dict,
        description="Which scoring factors contributed: no_imports, stale_90d, etc.",
    )


class CircularDependency(BaseModel):
    """A circular dependency detected via strongly connected components (MF-4)."""

    cycle_path: List[str]  # [A, B, C, A] — full cycle
    ref_sites: List[Evidence]  # The ref() calls creating the cycle
    suggestion: str  # Actionable fix recommendation


# =============================================================================
# dbt YAML Validation Models (M-5)
# =============================================================================


class DbtSourceTable(BaseModel):
    """A single source table definition from __sources.yml."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: Optional[str] = None
    loaded_at_field: Optional[str] = None
    columns: List[Dict[str, Any]] = Field(default_factory=list)
    meta: Dict[str, Any] = Field(default_factory=dict)


class DbtSource(BaseModel):
    """A source group from __sources.yml."""

    model_config = ConfigDict(extra="allow")

    name: str
    schema_: Optional[str] = Field(default=None, alias="schema")
    description: Optional[str] = None
    tables: List[DbtSourceTable] = Field(default_factory=list)


class DbtSourceConfig(BaseModel):
    """Top-level structure of __sources.yml (validated via Pydantic)."""

    model_config = ConfigDict(extra="allow")

    version: int = 2
    sources: List[DbtSource] = Field(default_factory=list)


class DbtProjectConfig(BaseModel):
    """Structure of dbt_project.yml (validated via Pydantic)."""

    model_config = ConfigDict(extra="allow")

    name: str = ""
    version: str = ""
    config_version: int = 2
    model_paths: List[str] = Field(default_factory=lambda: ["models"], alias="model-paths")
    seed_paths: List[str] = Field(default_factory=lambda: ["seeds"], alias="seed-paths")
    macro_paths: List[str] = Field(default_factory=lambda: ["macros"], alias="macro-paths")
    profile: Optional[str] = None


class DbtModelColumn(BaseModel):
    """A column definition from model .yml files."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: Optional[str] = None
    data_type: Optional[str] = None
    data_tests: List[Any] = Field(default_factory=list)


class DbtModelDef(BaseModel):
    """A model definition from model .yml files."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: Optional[str] = None
    columns: List[DbtModelColumn] = Field(default_factory=list)
    data_tests: List[Any] = Field(default_factory=list)


class DbtModelConfig(BaseModel):
    """Top-level structure of model .yml files."""

    model_config = ConfigDict(extra="allow")

    models: List[DbtModelDef] = Field(default_factory=list)
    unit_tests: List[Dict[str, Any]] = Field(default_factory=list)
    semantic_models: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: List[Dict[str, Any]] = Field(default_factory=list)
    saved_queries: List[Dict[str, Any]] = Field(default_factory=list)


# =============================================================================
# Container / Serialization Types
# =============================================================================


class AnalysisCheckpoint(BaseModel):
    """Progress persistence — save state every N files (SR-1)."""

    completed_files: List[str]
    partial_results: Dict[str, Any] = Field(default_factory=dict)
    checkpoint_time: str


class CodebaseGraph(BaseModel):
    """Top-level container for the entire analysis result.

    Serialized to .cartography/module_graph.json. Contains all nodes, edges,
    analysis findings, and metadata for downstream consumption.
    """

    repo_path: str
    analysis_timestamp: str
    analysis_version: str = "1.0.0"
    modules: List[ModuleNode] = Field(default_factory=list)
    datasets: List[DatasetNode] = Field(default_factory=list)
    functions: List[FunctionNode] = Field(default_factory=list)
    transformations: List[TransformationNode] = Field(default_factory=list)
    imports_edges: List[ImportsEdge] = Field(default_factory=list)
    produces_edges: List[ProducesEdge] = Field(default_factory=list)
    consumes_edges: List[ConsumesEdge] = Field(default_factory=list)
    calls_edges: List[CallsEdge] = Field(default_factory=list)
    configures_edges: List[ConfiguresEdge] = Field(default_factory=list)
    unresolved_refs: List[UnresolvedReference] = Field(default_factory=list)
    dead_code_candidates: List[DeadCodeCandidate] = Field(default_factory=list)
    circular_dependencies: List[CircularDependency] = Field(default_factory=list)
    analysis_errors: List[AnalysisError] = Field(default_factory=list)


# =============================================================================
# Semanticist LLM Structured Outputs
# =============================================================================

class LLMEvidence(BaseModel):
    """Specific evidence citation mapping to file paths and line numbers."""
    file: str
    line: int

class DayOneAnswer(BaseModel):
    """Enforced structured output for answering FDE Day-One questions."""
    question: str
    answer: str
    evidence: List[LLMEvidence] = Field(default_factory=list)

class ContextWindowBudget(BaseModel):
    """Token usage tracking across different model tiers."""
    bulk_input_tokens: int = 0
    bulk_output_tokens: int = 0
    synthesis_input_tokens: int = 0
    synthesis_output_tokens: int = 0
    estimated_cost_usd: float = 0.0
