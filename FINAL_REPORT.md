# The Brownfield Cartographer — Final Report

**Engineer:** Lidya Dagnew  
**Date:** March 15, 2026  
**Target Codebases:** `dbt-labs/jaffle-shop` (primary), `Roo-Code` (self-audit)

**Project Description:** The Brownfield Cartographer is an automated reverse-engineering knowledge graph that transforms raw codebases into queryable architectural intelligence, accelerating the Day-One onboarding process for Forward Deployed Engineers (FDEs).

---

## 1. RECONNAISSANCE.md — Manual Day-One Analysis

### Target: `dbt-labs/jaffle-shop`

I spent 30 minutes manually exploring the jaffle-shop repo. Below are my hand-written Day-One answers, which serve as ground truth for validating the Cartographer's automated output.

### Investigation Process

I did not start with documentation. I followed the data:

1. **Entry Point Hunt:** Opened `dbt_project.yml` to identify the project structure (`model-paths: ["models"]`, `seed-paths: ["seeds"]`).
2. **The Seed Lead:** Discovered `seeds/jaffle-data/` — six CSV files representing raw data. This is "Ground Zero."
3. **The Staging Bridge:** Traced `models/staging/__sources.yml` which declares `source('ecom', 'raw_customers')`. I initially assumed this pointed to a real database table, but cross-referencing with `dbt_project.yml` and the `seeds/` directory revealed the `raw` schema is actually static CSVs loaded by `dbt seed`. This indirection was the hardest thing to trace manually.
4. **Dependency Chain Tracing:** Searched for `ref('orders')` across all mart models. Found it in `customers.sql:11`, confirming the transformation chain `stg_orders → orders → customers`.
5. **Git Velocity Measurement:** Ran `git log --oneline -- <file> | wc -l` on each file to quantify commit counts as a proxy for change frequency.
6. **Debt & Documentation Hunt:** Grepped for `tests:` in `.yml` files to evaluate test coverage and searched for data dictionaries. The staging layer had basic tests, but mart business logic coverage was sparse.

#### Q1: Primary Data Ingestion Path
**Manual Finding:** Seed-to-Staging flow. Physical data enters via `seeds/jaffle-data/*.csv`. First-touch code is in `models/staging/stg_*.sql` which use `{{ source('ecom', ...) }}` macros.  
**Key Insight:** The `source()` macro creates an indirection — the SQL references a `raw` schema, but data is actually static CSVs loaded by `dbt seed`.

#### Q2: 3-5 Most Critical Outputs
1. `marts/customers` (7 commits) — the "Golden Record" combining customer + order data
2. `marts/orders` (12 commits) — core transactional truth with window functions
3. `marts/order_items` (9 commits) — junction of products, orders, and supplies

#### Q3: Blast Radius of `stg_orders` Failure
**Catastrophic.** `stg_orders` → `orders` → `customers`. Evidence: `models/marts/customers.sql:11` contains `ref('orders')`. All downstream marts depending on `orders` break.

#### Q4: Logic Concentration
Concentrated in the **Marts Layer**. Staging performs normalization (type casting, renaming). Marts contain business logic: LTV aggregations, `customer_type` classification.

#### Q5: Git Velocity
| Path | Commits | Role |
|:---|:---:|:---|
| `models/marts/orders.sql` | 12 | Core Transaction Logic |
| `models/marts/order_items.sql` | 9 | Granular Details |
| `models/staging/__sources.yml` | 9 | Metadata Registry |
| `models/marts/customers.sql` | 7 | Identity/LTV Logic |

### Difficulty Analysis
1. The `source()` → seed indirection was the hardest to trace manually
2. The `cents_to_dollars` macro required cross-file tracing
3. `metricflow_time_spine` appeared as dead code but serves MetricFlow joins
4. Jinja templating in SQL makes static parsing significantly harder

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    CLI Entry Point                       │
│              (analyze | query | ui)                      │
└────────────┬────────────────────────────────────────────┘
             │
             ▼
┌─────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                          │
│          (Manages pipeline + incremental mode)           │
└────┬───────────┬───────────┬───────────┬───────────────┘
     │           │           │           │
     ▼           ▼           ▼           ▼
┌─────────┐ ┌──────────┐ ┌───────────┐ ┌──────────┐
│SURVEYOR │ │HYDROLOGIST│ │SEMANTICIST│ │ ARCHIVIST│
│Phase 1  │ │Phase 2    │ │Phase 3    │ │ Phase 4  │
│         │ │           │ │           │ │          │
│tree-sitter│ │sqlglot   │ │LiteLLM   │ │CODEBASE  │
│PageRank │ │dbt YAML  │ │Purpose    │ │.md       │
│Git Vel. │ │Lineage   │ │Statements │ │Brief     │
│Dead Code│ │Blast Rad.│ │Domain     │ │Trace Log │
│SCC      │ │Sources/  │ │ Clustering│ │          │
│         │ │ Sinks    │ │Doc Drift  │ │          │
└────┬────┘ └────┬─────┘ └────┬──────┘ └────┬─────┘
     │           │            │              │
     └───────────┴────────────┴──────────────┘
                       │
                       ▼
          ┌──────────────────────────┐
          │    KNOWLEDGE GRAPH       │
          │  (NetworkX + Pydantic)   │
          │                          │
          │  ModuleNode, DatasetNode │
          │  FunctionNode, Transform │
          │  IMPORTS, PRODUCES,      │
          │  CONSUMES, CALLS, CONFIG │
          └────────────┬─────────────┘
                       │
                       ▼
          ┌──────────────────────────┐
          │    NAVIGATOR AGENT       │
          │  (LangGraph + 4 Tools)   │
          │                          │
          │  find_implementation()   │
          │  trace_lineage()         │
          │  blast_radius()          │
          │  explain_module()        │
          └──────────────────────────┘
```

### Pipeline Design Rationale

The architecture separates deterministic static analysis from LLM-based semantic reasoning. The Surveyor and Hydrologist operate purely on static code structure using tree-sitter and sqlglot, ensuring reproducibility, low cost, and zero API dependency. The Semanticist layer introduces LLM reasoning only after structural graphs are fully constructed, allowing purpose extraction and domain clustering to operate on complete context without repeatedly scanning raw code.

The Knowledge Graph (NetworkX + Pydantic) serves as the central system state because codebase intelligence problems are fundamentally relational. Module imports, dataset lineage, and function calls naturally map to directed graph edges, making NetworkX an appropriate representation with native support for PageRank, topological sort, BFS/DFS traversal, and strongly connected component detection — all algorithms the Cartographer actively uses. A relational database would require expensive JOINs for graph traversals; a graph database (e.g., Neo4j) would add deployment complexity inappropriate for a portable, single-command FDE tool.

The Surveyor → Hydrologist → Semanticist → Archivist ordering is deliberate: each agent builds on its predecessor's output. The Surveyor produces the structural graph that the Hydrologist extends with data lineage edges. The Semanticist enriches nodes with LLM-generated purpose statements using both structural and lineage context. The Archivist then synthesizes all prior output into human-readable artifacts. This ordering minimizes redundant computation and ensures each agent has maximum context available. From a performance scaling perspective, the decoupled agent architecture allows the static analysis phases (Surveyor, Hydrologist) to run locally in seconds, while the computationally expensive Semanticist phase can be parallelized via asynchronous LLM inference batches using `asyncio` and `LiteLLM`.

---

## 3. Accuracy Analysis — Manual vs. System-Generated

### Jaffle Shop Comparison

| Question | Manual Answer | System Answer | Evidence | Correct? |
|:---|:---|:---|:---|:---:|
| **Q1: Ingestion Path** | Seeds → Staging via `source('ecom', ...)` | 6 sources: `ecom.raw_customers`, `ecom.raw_orders`, etc. + 13 staging models | `onboarding_brief.md` §1: "Sources identified (6)" + `datasets.json` listing all 6 DatasetNode entries | ✅ |
| **Q2: Critical Outputs** | `customers`, `orders`, `order_items` | `customers` (PR=0.110), `orders` (PR=0.088), `order_items` (PR=0.068) — same top 3, correctly ranked | `module_graph.json` → ModuleNode `models/marts/customers.sql` pagerank_score: 0.1104 | ✅ |
| **Q3: Blast Radius** | `stg_orders` → `orders` → `customers` (catastrophic) | `customers.sql` → 1 downstream node (`dataset:customers`). Identifies hub but blast from `stg_orders` specifically not auto-traced | `onboarding_brief.md` §3 + `lineage_graph.json` edge: `transformation:orders` → `dataset:orders` | ⚠️ Partial |
| **Q4: Logic Concentration** | Marts layer (business logic), Staging (normalization) | Marts: 13 files, complexity 34. Staging: 13 files, complexity 13 | `onboarding_brief.md` §4 + `modules.json` complexity_score per module | ✅ |
| **Q5: Git Velocity** | `orders.sql` (12 commits), `order_items.sql` (9 commits) | `stg_orders.sql` (velocity: 0.03) | `modules.json` → change_velocity_30d field. Low because repo has minimal recent activity | ⚠️ Limited |

**Summary:** The system correctly identifies ingestion paths, critical outputs, and logic concentration, ranking them with precision via PageRank and module counting. Blast radius and git velocity analysis were partially accurate due to graph scope limitations (narrow traversal depth) and repository activity levels (sparse 30-day activity).

---

## 4. Limitations

### Fundamental System Limitations & Mitigations

1. **Static Analysis Cannot Resolve Dynamic Code Generation:** The Cartographer strips Jinja tags (`{{ ref('...') }}`, `{{ source('...', '...') }}`) using regex before feeding SQL to sqlglot. While this works for standard dbt patterns, any codebase that generates SQL dynamically (e.g., via Python string templates, Jinja macros with conditional logic, or runtime query builders) will produce incomplete lineage graphs. This is a fundamental limitation of static analysis — resolving dynamic code requires runtime instrumentation or symbolic execution, which is outside the Cartographer's scope.
   - *Mitigation:* Integrate dbt's compiled `target/manifest.json` as a fallback data source to capture post-compilation lineage, bridging the gap between static analysis and runtime resolution.

2. **Cross-Language Import Resolution Requires Build System Awareness:** For TypeScript codebases (like Roo-Code), the Surveyor detects imports via tree-sitter AST but cannot resolve aliased paths (e.g., `@/core/task`) without parsing `tsconfig.json` path mappings. Similarly, Python namespace packages and `sys.path` manipulation create import chains that static analysis alone cannot fully resolve. The Cartographer currently handles standard relative/absolute imports but not build-system-mediated resolution.
   - *Mitigation:* Implement language-specific "Path Resolver" strategy classes that parse `tsconfig.json`, `package.json`, or `setup.py` metadata before AST traversal begins.

3. **Dead Code Detection Assumes Single-Language Import Semantics:** The 4-factor dead code scoring (no imports, stale, no tests, no exposure) implicitly assumes Python-style import patterns. In monorepos with compiled output directories (e.g., Roo-Code's `out/` directory mirrors `src/`), the scoring flags build artifacts as dead code because no explicit import edges connect them to their source files. This produced 2,591 false positives (98.7%) in the Roo-Code analysis.
   - *Mitigation:* Allow users to define `--ignore-paths` in the CLI to exclude build output directories (`out/`, `dist/`, `build/`) from analysis scope, or auto-detect standard ignore patterns from `.gitignore`.

4. **LLM Semantic Grounding vs. Hallucination:** Purpose statements generated by the LLM are grounded in code snippets passed via prompt, but the system cannot verify whether the LLM's interpretation is semantically correct. In the Roo-Code analysis, some purpose statements included fabricated code examples rather than concise business-purpose descriptions. Without a ground-truth validation loop, LLM-generated semantic metadata must be treated as approximate.
   - *Mitigation:* Implement a "Reviewer" self-reflection prompt step where the LLM specifically scores its own generated purpose statement against brevity and accuracy constraints before committing it to the graph.

5. **Git Velocity Window Bias:** The 30-day velocity window produces low-entropy results when analyzing repos with infrequent commits (like jaffle-shop). A configurable window or all-time commit count would give richer signals. This is a design trade-off: shorter windows are more relevant for active codebases (the typical FDE scenario), but produce sparse data for archived or stable projects.
   - *Mitigation:* Make the velocity window a configurable CLI parameter (`--velocity-days 90`), and fallback to an all-time commit count if the 30-day commit volume is below a minimum threshold.

---

## 5. FDE Applicability

In a real client engagement, I would deploy the Brownfield Cartographer within the first hour of accessing a new codebase. The `CODEBASE.md` output alone eliminates the "cold start" problem — instead of spending my first day grepping through files and asking colleagues for context, I would have an immediate architectural map with PageRank-identified critical paths, data lineage sources and sinks, and auto-generated Day-One answers.

**Deployment Scenario A: Production Incident Response:** A client reports that their `daily_revenue` metric dashboard has been showing incorrect numbers since last Tuesday. Without the Cartographer, I would spend hours tracing the pipeline manually — searching for which SQL model produces `daily_revenue`, what upstream tables it depends on, and what changed recently. With the Cartographer, I would run `blast_radius('revenue.sql')` to immediately see every upstream dependency, then cross-reference with the git velocity map to identify which files in the dependency chain were modified around Tuesday. The lineage graph answers "what feeds this metric?" in seconds. The git velocity answers "what changed?" in seconds. Together, they reduce a half-day investigation to a 10-minute targeted diagnosis.

**Deployment Scenario B: Technical Debt Assessment for Cloud Migration:** Before replatforming a legacy backend, the client wants to know which components to deprecate versus rewrite. By querying the Cartographer's Knowledge Graph, I can immediately identify the intersection of high dead-code likelihood (`is_dead_code_candidate=True`) and low git velocity. This provides a data-driven justification for dropping specific modules during the migration, reducing scope and derisking the project on Day One.

The `CODEBASE.md` can also be injected directly into any AI coding assistant (Claude, Cursor, etc.) as system context, giving it instant architectural awareness. For data engineering codebases specifically, the lineage graph is the most valuable output — being able to answer "what breaks if I change this table?" within minutes rather than hours is the difference between a productive FDE and one who is still lost on Day 3. Ultimately, the Cartographer transforms the typical "Day-3 understanding" of a codebase into a Day-1 capability, significantly accelerating FDE onboarding velocity.

---

## 6. Self-Audit Results (Roo-Code)

### Target: Roo-Code (2,624 modules, TypeScript)

The Cartographer was run against Roo-Code as a self-audit exercise. The RECONNAISSANCE.md (written manually) was compared against the system-generated `CODEBASE.md` and `onboarding_brief.md`.

### Key Findings

| Manual (RECONNAISSANCE.md) | System (.cartography_roo) | Match? |
|:---|:---|:---:|
| Entry point: `src/extension.ts` via `activate()` | Identified 21 entry points including extension files | ✅ |
| Critical module: `src/core/task/Task.ts` (~80 changes) | High velocity: `src/core/task/Task.ts` (velocity: 0.17) | ✅ |
| Blast radius of Task.ts: "Total Failure" | 2,591 dead code candidates flagged | ⚠️ Over-flagging |
| Business logic in `src/core/task/` and `src/api/` | Domain clustering: Core (243), Api (implicit in providers) | ✅ |

### Discrepancy Explained

The main discrepancy is in **dead code detection**. My manual RECONNAISSANCE correctly identified that most modules in Roo-Code are actively used — the `out/` directory contains compiled JavaScript mirrors of the `src/` TypeScript files. The Cartographer flagged 98.7% of modules as dead code because its import-graph analysis doesn't link `out/*.js` files back to their `src/*.ts` sources. This reveals a genuine limitation: the Cartographer's dead code scoring assumes a single-language, single-build-output codebase. For monorepos with build artifacts checked in, an awareness of `tsconfig.json` output paths would eliminate these false positives.

**A second discrepancy** is in purpose statement quality. The manual audit identified `src/core/task/Task.ts` as "the heart of the agentic loop" — a concise, business-purpose description. The system's LLM-generated statements for some modules were verbose and included code examples rather than purpose-focused summaries. This is a solvable prompt engineering issue.

Despite these limitations, the Cartographer successfully identified the correct entry points, high-velocity modules, and domain clusters across a 2,600-module TypeScript codebase, proving the AST-based scaling architecture is fundamentally sound.

### Next Steps for System Maturity

This self-audit validates the core architecture while highlighting concrete roadmap items for the next development iteration:
1. **Resolution Agent:** Add a pre-processing step that parses `tsconfig.json` and `package.json` to map module aliases to absolute file paths before tree-sitter AST construction to fix TypeScript imports.
2. **Build Exclusion Profiles:** Pass standard build directories (`out/`, `dist/`) to the Surveyor's ignore list to immediately fix the 98.7% dead code false positive rate.

---

## 7. Conclusion

The Brownfield Cartographer successfully demonstrates that the cognitive load of a new codebase can be systematically reduced. By combining deterministic AST parsing, data lineage extraction, and LLM-powered semantic reasoning into a unified graph, the tool provides FDEs with actionable architectural awareness on Day One. The self-audit on Roo-Code proved the architecture scales to thousands of files, while the Jaffle Shop analysis validated its precision in identifying critical data paths. With minor improvements to import resolution and prompt tuning, this system represents a foundational capability for rapid onboarding in production environments.

---

## Appendix: Generated Artifacts

### Jaffle Shop (`.cartography/`)
- `CODEBASE.md` — 103 lines, 38 modules indexed
- `onboarding_brief.md` — 79 lines, all 5 questions answered
- `module_graph.json` — 85 KB, full Pydantic-serialized graph
- `lineage_graph.json` — 41 KB, 32 lineage nodes, 30 edges
- `module_graph.png` — 865 KB, PageRank × Git Velocity visualization
- `cartography_trace.jsonl` — 10 pipeline stage entries

### Roo-Code (`.cartography_roo/`)
- `CODEBASE.md` — 2,713 lines, 2,624 modules indexed
- `onboarding_brief.md` — 381 lines, all 5 questions answered
- `module_graph.json` — 5.6 MB, full Pydantic-serialized graph
- `lineage_graph.json` — 7.9 KB, 16 lineage nodes
- `module_graph.png` — 7.8 MB, large-scale visualization
- `cartography_trace.jsonl` — 10 pipeline stage entries
