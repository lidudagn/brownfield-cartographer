# Demo Video Script (6 Minutes)

> Record with OBS or screen recorder. Show terminal + VS Code side by side.

---

## Minutes 1–3: REQUIRED

### Step 1: The Cold Start (~1 min)

**Say:** "I'm running the Brownfield Cartographer on an unfamiliar codebase — dbt's jaffle-shop."

```bash
# Start timer visible on screen
cd ~/Videos/week\ 4/brownfield-cartographer

# Run the analysis
uv run cartographer analyze --repo-path "../jaffle-shop" --output-dir ".cartography" --verbose
```

**While it runs, say:** "The Surveyor parses ASTs with tree-sitter, the Hydrologist builds data lineage with sqlglot, the Semanticist generates purpose statements, and the Archivist writes the final artifacts."

**When complete, show the output summary and then open the generated file:**

```bash
cat .cartography/CODEBASE.md
```

**Say:** "CODEBASE.md was generated in [X] seconds with [38] modules indexed."

---

### Step 2: The Lineage Query (~1 min)

**Say:** "Now I'll query the knowledge graph to trace data lineage."

```bash
uv run cartographer query
```

**In the REPL, type:**

```
lineage customers upstream
```

**Say:** "The system traces upstream from the `customers` dataset and shows that it depends on `stg_customers` and `orders`, which in turn depends on `order_items` and `stg_orders`. Every result cites the source file and analysis method."

**Then type:**

```
lineage ecom.raw_orders downstream
```

**Say:** "From the raw source `ecom.raw_orders`, the downstream traversal shows it flows through `stg_orders` into `orders`, then into `customers` — confirming the full pipeline path."

---

### Step 3: The Blast Radius (~1 min)

**Say:** "Now I'll check what breaks if a critical module changes."

**In the REPL, type:**

```
blast models/staging/stg_orders.sql
```

**Say:** "The blast radius shows [N] downstream nodes that would be affected if `stg_orders` changes — including `orders`, `order_items`, `customers`. This matches my manual reconnaissance finding that `stg_orders` failure is catastrophic."

**Then type:**

```
exit
```

---

## Minutes 4–6: MASTERY

### Step 4: The Day-One Brief (~1 min)

**Say:** "Let me show the auto-generated FDE Day-One Brief."

```bash
cat .cartography/onboarding_brief.md
```

**Read Q1 and Q2 answers aloud, then verify:**

**Say:** "The brief says customers.sql has PageRank 0.110 and depends on orders and stg_customers. Let me verify."

```bash
# Open the actual file
head -15 ../jaffle-shop/models/marts/customers.sql
```

**Say:** "Confirmed — line 11 shows `ref('orders')` and line 8 shows `ref('stg_customers')`. The Cartographer's answer is correct."

---

### Step 5: Living Context Injection (~1 min)

**Say:** "Now I'll show how CODEBASE.md gives an AI agent instant architectural awareness."

**Open a new AI chat (Claude/Cursor) WITHOUT context, ask:**

> "What is the most critical module in the jaffle-shop codebase?"

**Show the generic/unhelpful response.**

**Then paste CODEBASE.md content as context and ask the same question.**

**Say:** "With the injected context, the agent correctly identifies `customers.sql` as the highest-PageRank module and explains its role as the Golden Record. This is the living context advantage."

---

### Step 6: The Self-Audit (~1 min)

**Say:** "Finally, I ran the Cartographer on a second codebase — Roo-Code, a 2,624-module TypeScript project."

```bash
# Show the Roo-Code results
head -80 .cartography_roo/CODEBASE.md
```

**Say:** "The system correctly identified `src/core/task/Task.ts` as the highest-velocity file with 0.17 change frequency. However, it flagged 98.7% of modules as dead code — a known limitation because our import resolution doesn't handle TypeScript path aliases. This is documented in the FINAL_REPORT.pdf under Limitations."

**Say:** "This discrepancy between manual reconnaissance and automated output is exactly the kind of failure awareness that makes the tool trustworthy — we know where it works and where it doesn't."

---

## Quick Reference — Key Commands

```bash
# Analyze
uv run cartographer analyze --repo-path "../jaffle-shop" --output-dir ".cartography" --verbose

# Query REPL
uv run cartographer query

# REPL commands:
lineage customers upstream
lineage ecom.raw_orders downstream
blast models/staging/stg_orders.sql
find revenue calculation
explain models/marts/customers.sql
exit
```
