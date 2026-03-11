# RECONNAISSANCE.md: Phase 0 Manual Audit Log (v2)

**Engineer:** FDE-01 (Antigravity)
**Target:** `dbt-labs/jaffle-shop`
**Duration:** 30-minute deep dive

## The Investigative Process: How I mapped this "Blind"

I didn't start with a high-level summary. I started by following the data.

1.  **Entry Point Hunt**: I looked for a `README.md` and `dbt_project.yml`. The project is small but has the standard dbt "layered" structure.
2.  **The Seed Lead**: I found `seeds/jaffle-data`. This is the "Ground Zero."
    ```yaml
    # models/staging/__sources.yml
    sources:
      - name: ecom
        schema: raw
        tables:
          - name: raw_customers
    ```
3.  **The Staging Bridge (The "Lie")**: The code claims to point to a `raw` schema, but the data is physically static CSVs.
    > [!WARNING]
    > For the Cartographer, this "Staging Bridge" lie is a critical edge case. If the parser only looks at SQL `source()` calls without resolving the YAML metadata to the physical filesystem (seeds), it will report a broken upstream dependency. The Cartographer must unify the logical "raw" schema with the physical `seeds/` path.
4.  **The Marts Logic**: I spent 10 minutes tracing the relationship between `customers.sql` and `orders.sql`.

---

## The Five FDE Day-One Questions (Evidence-Backed)

### 1. What is the primary data ingestion path?
It's a "Seed-to-Staging" flow. 
- **Physical Source**: `seeds/jaffle-data/*.csv`.
- **First-touch Code**: `models/staging/stg_*.sql` which use the `{{ source('ecom', ...) }}` macro. 

### 2. What are the 3-5 most critical output datasets?
1.  **`marts/customers`** (7 commits): The "Golden Record." 
2.  **`marts/orders`** (12 commits): The transactional truth.
    ```sql
    -- models/marts/orders.sql (Logic Fragment)
    row_number() over (
        partition by customer_id
        order by ordered_at asc
    ) as customer_order_number
    ```
3.  **`marts/order_items`** (9 commits): The junction of products and supplies.

### 3. What is the blast radius of a `stg_orders` failure?
**Catastrophic.** 
- `stg_orders` (6 commits) -> `marts/orders` -> `marts/customers`.
- **Evidence**: `marts/customers.sql` line 11 explicitly `ref('orders')`.
- **Radius**: All downstream marts depending on `orders`, including `customers`. This represents the majority of business-facing analytics models.


### 4. Logic Concentration: Where is the "Brain"?
Concentrated in the **Marts Layer**. 
- **Staging** is just "Janitor work": casting types, renaming `id` to `customer_id`.
- **Marts** is where the business lives: LTV aggregations and `customer_type` classification (returning vs new).

### 5. Git Velocity: Quantified (All-Time Commits)
| Path | Commits | Role |
| :--- | :--- | :--- |
| `models/marts/orders.sql` | 12 | Core Transaction Logic |
| `models/marts/order_items.sql` | 9 | Granular Details |
| `models/staging/__sources.yml` | 9 | Metadata Registry |
| `models/marts/customers.sql` | 7 | Identity/LTV Logic |
| `models/staging/stg_orders.sql` | 6 | High-Impact Source |

---

## Technical Friction & Cartographer Design Hints

### The "Hard" Problems found during manual Trace:
- **Implicit Cardinalities**: Window functions such as `partition by customer_id` suggest grouping semantics that may indicate 1:N relationships. The Cartographer should flag these patterns as heuristic signals rather than definitive cardinality.
- **Dynamic References**: I noticed some models use macros. 
    > [!CAUTION]
    > **Messy Case Hunt**: If `ref()` is wrapped in a macro (e.g., `{{ ref(var('model_name')) }}`), simple static analysis fails. The Cartographer must either handle macro substitution or flag "Unresolved Dynamic Linkage."

### Visualization Hints for the Archivist:
- **Lineage**: Represented as a DAG where node size corresponds to **Git Velocity** (Commits) and color intensity corresponds to **Complexity** (Lines of Logic).
- **Blast Radius**: Highlight a node (e.g., `stg_orders`) and auto-color all downstream nodes in red to visualize the impact.

### Priorities for Automation:
1.  **S-Expression Queries**: Extract `partition by` from SQL to auto-document relationship types.
2.  **Cross-Boundary Parsing**: Bridge the YAML/SQL/CSV gap to demystify the "Staging Bridge."
3.  **Dynamic Reference Flagging**: Detect and warn about non-static `ref()` calls.

---

## Model Dependencies (Full DAG)

```text
seeds (CSVs: raw_customers, raw_orders, raw_items, raw_products, raw_stores, raw_supplies)
  │
  ▼
┌─────────────┬─────────────┬──────────────┬──────────────┬──────────────┬────────────────┐
│stg_customers│  stg_orders │stg_order_items│ stg_products │stg_locations │  stg_supplies  │
└──────┬──────┴──────┬──────┴──────┬───────┴──────┬───────┴──────┬───────┴───────┬────────┘
       │             │             │              │              │               │
       │             │             ├──────────────┤              │               │
       │             │             ▼              ▼              │               │
       │             │        order_items ◄── products           │               │
       │             │             │                             │               │
       │             │             ▼                             ▼               ▼
       │             └──────► orders                        locations        supplies
       │                        │
       └────────────────────────┤
                                ▼
                            customers

                       metricflow_time_spine (standalone, no refs)
```

### Key Observations
- **Staging models** (prefix `stg_`) are 1:1 wrappers around raw source tables
- **`order_items`** is the junction: joins `stg_order_items` + `stg_products` + `stg_supplies`
- **`orders`** aggregates from `order_items` + `stg_orders`
- **`customers`** is the "Golden Record": joins `stg_customers` + `orders`
- **`locations`**, **`products`**, **`supplies`** are simpler pass-through marts
- **`metricflow_time_spine`** is an isolated utility (generates a date spine via `generate_series`)

---

## What Was Hardest / Where I Got Lost

1. **The `source()` → seed indirection**: I initially assumed `source('ecom', 'raw_customers')` pointed to a real database table. It took reading `dbt_project.yml` + `__sources.yml` + cross-referencing the `seeds/` directory to realize the "raw" schema is actually static CSVs loaded by `dbt seed`. A parser that only follows SQL references would report broken upstream dependencies.
2. **The `cents_to_dollars` macro**: This custom macro is used in 4 staging models. Without reading `macros/cents_to_dollars.sql`, I couldn't tell if it was a simple cast or had business logic. Tracing macro dependencies across files was manual and error-prone.
3. **Window function semantics**: Understanding the `partition by customer_id` in `orders.sql` required reading the full CTE chain to understand that it's computing `customer_order_number`, not just grouping.
4. **The `metricflow_time_spine`**: This model has zero `ref()` calls and uses `generate_series()` — a pure utility. I initially thought it was orphaned dead code until I understood its role in MetricFlow.

