# The Brownfield Cartographer

> Multi-agent codebase intelligence system for rapid FDE onboarding in production environments.

The Brownfield Cartographer is designed to automatically ingest a complex "brownfield" codebase (such as an undocumented dbt project) and build a queryable Codebase Knowledge Graph detailing data flows, code metrics, and architectural structure.

Welcome to **Phase 2: The Hydrologist Agent** (Data Flow & Lineage).

## Overview

The system orchestrates a multi-step analysis pipeline combining two agents:

### Surveyor Agent (Phase 1)
1. Multi-language AST parsing (Python, SQL, YAML) via `tree-sitter`
2. SQL dependency extraction and column-level lineage via `sqlglot`
3. dbt configuration parsing mapping data sources and models
4. Entry point detection across dbt pipelines, Python CLIs, and Airflow DAGs
5. Git velocity extraction (computing unique change days)
6. PageRank scaling to identify structural and architectural "hubs"
7. Circular dependency detection (Strongly Connected Components)
8. Dead code candidate scoring (confidence derived from 4 key codebase factors)

### Hydrologist Agent (Phase 2)
9. Data lineage graph construction (Dataset → Transformation → Dataset)
10. Blast radius analysis via shortest-path traversal
11. Source/sink identification (in-degree=0 / out-degree=0 nodes)
12. Cycle detection in lineage DAGs
13. Path-based lineage tracing between any two nodes

### Outputs
14. Output serialization to standard `JSON` format (`module_graph.json`, `lineage_graph.json`)
15. `matplotlib` network graph visualization
16. `cartography_trace.jsonl` audit log

## Installation

The Brownfield Cartographer uses `pyproject.toml` to manage standard dependencies.

**Requirements:**
- Python `>= 3.10`
- Git

```bash
# Clone the repository
git clone https://github.com/organization/brownfield-cartographer.git
cd brownfield-cartographer

# Install using pip (or uv)
pip install -e .[dev]
```

## Usage

The Cartographer exposes a CLI tool via `click`.

```bash
cartographer analyze --repo-path /path/to/target/codebase
```

### Options
- `--repo-path` (Required): The absolute or relative path to the repo to analyze.
- `--output-dir`: Where to save reports (default: `.cartography`).
- `--dialect`: SQL dialect for parsing. Supports `auto`, `postgres`, `snowflake`, `bigquery`, `duckdb` (default: `auto`).
- `--workers`: Number of parallel structural threads to run (default: `4`).
- `--days`: Lookback window for git velocity analysis (default: `30`).
- `--dry-run`: Performs file discovery phase without executing parsing logic.
- `--verbose`: Enable debug-level logging.

## Outputs

Analysis generates the following files in the target `--output-dir` (default: `.cartography/`):

1. **`module_graph.json`**
   The definitive, serialized Pydantic JSON graph of the target codebase. This includes:
   - Extracted objects (`ModuleNode`, `DatasetNode`, `FunctionNode`, `TransformationNode`)
   - Links and data flows (`ImportsEdge`, `ProducesEdge`, `ConsumesEdge`, `CallsEdge`, `ConfiguresEdge`)
   - Every edge and finding contains an `Evidence` trace (file, line number, and raw snippet)
   - Extracted Data Lineage, Circular Dependencies, and Dead Code calculations.

2. **`lineage_graph.json`**
   A focused subset containing transformations, datasets, and lineage edges for data flow analysis.

3. **`module_graph.png`**
   A static `matplotlib` rendering of the graph where:
   - Node size = Codebase PageRank importance
   - Node color = Git Change Velocity (Heatmap)
   - Edges = Imports / Calls / Produces relations

4. **`cartography_trace.jsonl`**
   Audit log of every analysis action with timestamps and metrics.

## Known Gaps (Phase 2)
- **Semanticist Agent (Phase 3):** LLM-powered purpose statements, domain clustering, and Day-One question answering are not yet implemented.
- **Navigator Agent (Phase 4):** Interactive query interface with `find_implementation`, `trace_lineage`, `blast_radius`, and `explain_module` tools not yet built.
- **Deep Python Data Lineage:** Currently limited to top-level structural definitions. Intra-function control flow is not parsed into variables.
- **Remote Data Warehouses:** Does not reach into a Snowflake/BigQuery schema to detect actual drift — schema snapshots map only to what is statically documented in the YAMLs vs `sqlglot` output.
