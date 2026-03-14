# Phase 0 Manual Audit Log (v2)

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
    > The `source()` call creates an indirection. Although the SQL refers to a `raw` schema table, the data is actually provided through CSV seeds defined in the YAML configuration. This makes dependency tracing harder because the logical source does not directly map to a physical database table.
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
- **Evidence**: 
  `models/marts/customers.sql:11`
  `ref('orders')`
- **Radius**: All downstream marts depending on `orders`, including `customers`. This represents the majority of business-facing analytics models.


### 4. Logic Concentration: Where is the "Brain"?
Concentrated in the **Marts Layer**. 
- **Staging** primarily performs normalization tasks: type casting, renaming, and light transformations.
- **Marts** is where the business lives: LTV aggregations and `customer_type` classification (returning vs new).

### 5. Git Velocity: Quantified (All-Time Commits)

High commit velocity often indicates modules where business logic is evolving quickly, making them likely maintenance hotspots.

*(Measured via `git log --oneline -- <file> | wc -l`)*

| Path | Commits | Role |
| :--- | :--- | :--- |
| `models/marts/orders.sql` | 12 | Core Transaction Logic |
| `models/marts/order_items.sql` | 9 | Granular Details |
| `models/staging/__sources.yml` | 9 | Metadata Registry |
| `models/marts/customers.sql` | 7 | Identity/LTV Logic |
| `models/staging/stg_orders.sql` | 6 | High-Impact Source |

## Core Architecture Observation (Materializations & Naming)
**Naming conventions indicate clear layering:**
- `stg_*` → staging layer (no complex joins)
- `(no prefix)` → marts layer (business logic)

This convention makes automated layer detection straightforward.

Most **marts** use `table` materialization (heavy reads, complex joins).
Most **staging models** are configured as `views` (lightweight casting/renaming). This fits standard dbt best practices perfectly.

**Evidence from `dbt_project.yml`**:
```yaml
models:
  jaffle_shop:
    materialized: view # Staging defaults to view
    marts:
      materialized: table # Marts overridden to table
```

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
       │             ├──────────────┘              │               │
       │             ▼                             │               │
       │        order_items ◄── stg_products       │               │
       │             │                             │               │
       │             └───┬─────────┘                             ▼               ▼
       │                 ▼                                   locations        supplies
       │               orders
       │                 │
       └────────┬────────┘
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
4. **The `metricflow_time_spine`**: This model has zero `ref()` calls and uses `generate_series()` — a pure utility. The important insight is that this model is **used by MetricFlow to support time-based metric joins**. Without understanding this, it looks like dead code.
5. **Jinja templating in SQL**: Static SQL parsers struggle significantly with dynamic template tags like `{{ source('ecom','raw_customers') }}` and `{{ ref('orders') }}` without an active dbt compilation context. This makes extracting reliable static edges much harder than plain SQL parsing.

