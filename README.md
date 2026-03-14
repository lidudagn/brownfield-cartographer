# The Brownfield Cartographer

> Multi-agent codebase intelligence system for rapid FDE onboarding in production environments.

The Brownfield Cartographer automatically ingests a complex "brownfield" codebase (e.g., an undocumented dbt project) and builds a queryable Codebase Knowledge Graph detailing data flows, code metrics, and architectural structure.

## Architecture

The system orchestrates a multi-step analysis pipeline combining three agents:

### Surveyor Agent (Phase 1)
1. Multi-language AST parsing (Python, SQL, YAML) via `tree-sitter`
2. SQL dependency extraction and column-level lineage via `sqlglot`
3. dbt configuration parsing mapping data sources and models
4. Entry point detection across dbt pipelines, Python CLIs, and Airflow DAGs
5. Git velocity extraction (computing unique change days)
6. PageRank scaling to identify structural and architectural "hubs"
7. Circular dependency detection (Strongly Connected Components)
8. Dead code candidate scoring (4-factor confidence: no imports, stale, no tests, no exposure)

### Hydrologist Agent (Phase 2)
9. Data lineage graph construction (Dataset → Transformation → Dataset)
10. Python data flow integration (pandas/PySpark reads/writes)
11. Blast radius analysis via shortest-path traversal
12. Source/sink identification (in-degree=0 / out-degree=0 nodes)
13. Cycle detection in lineage DAGs
14. Path-based lineage tracing between any two nodes
15. Upstream/downstream dependency queries

### Semanticist Agent (Phase 3)
16. LLM-powered purpose statements for every module
17. Documentation drift detection
18. Domain clustering via semantic similarity
19. Five FDE Day-One question answering with evidence citations
20. Context window budgeting with tiered model selection

### Outputs
21. Output serialization to standard JSON format (`module_graph.json`, `lineage_graph.json`)
22. `matplotlib` network graph visualization (`module_graph.png`)
23. `onboarding_brief.md` — Five FDE Day-One answers (LLM or static fallback)
24. `cartography_trace.jsonl` audit log
25. Schema drift detection (SQL vs YAML column comparison)

## Installation

**Requirements:**
- Python `>= 3.10`
- Git

```bash
# Clone the repository
git clone https://github.com/organization/brownfield-cartographer.git
cd brownfield-cartographer

# Install using pip (or uv)
pip install -e .[dev]

# Or using uv
uv pip install -e .[dev]
```

## Usage

The Cartographer exposes a CLI tool via `click`.

```bash
# Analyze a local repository
cartographer analyze --repo-path /path/to/target/codebase

# Analyze a remote GitHub repository (auto-clones, depth=1)
cartographer analyze --repo-path https://github.com/dbt-labs/jaffle_shop

# Query the generated intelligence graph
cartographer query --query "What is the primary data ingestion path?"

# Launch the interactive web UI
cartographer ui
```

### Quick Start
```bash
# 1. Analyze 
cartographer analyze --repo-path https://github.com/dbt-labs/jaffle_shop

# 2. Ask questions via interactive REPL / LangGraph 
cartographer query

# 3. Or launch the Streamlit Web UI
cartographer ui
```

### Options
- `--repo-path` (Required): Local path OR remote Git URL (`https://github.com/org/repo`) to analyze. GitHub, GitLab, and Bitbucket URLs are auto-detected and shallow-cloned.
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
   - Circular Dependencies, Dead Code, and Schema Drift reports

2. **`lineage_graph.json`**
   A focused subset containing transformations, datasets, and lineage edges for data flow analysis.

3. **`onboarding_brief.md`**
   The FDE Day-One Brief answering five critical onboarding questions with evidence citations.

4. **`module_graph.png`**
   A static `matplotlib` rendering of the graph where:
   - Node size = Codebase PageRank importance
   - Node color = Git Change Velocity (Heatmap)
   - Edges = Imports / Calls / Produces relations

5. **`cartography_trace.jsonl`**
   Audit log of every analysis action with timestamps and metrics.

## Known Gaps
- **Remote Data Warehouses:** Does not reach into Snowflake/BigQuery schemas to detect actual drift — schema snapshots only cover what is statically documented in YAMLs vs `sqlglot` output.
