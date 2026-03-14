# CODEBASE.md — Living Architectural Context
**Generated:** 2026-03-15T00:33:58.472302
**Repository:** `/home/lidya/Videos/week 4/brownfield-cartographer/../jaffle-shop`

## Architecture Overview

This codebase contains **38 modules** (17 yaml, 15 jinja_sql, 6 csv) totaling **155,093 lines of code**. It is organized into 7 inferred domains: Models (26), Seeds (6), Macros (2), Taskfile.Yml (1), Dbt Project.Yml (1). There are **13 entry points** and **13 data transformations** tracked.

## Critical Path

The most architecturally significant modules (by PageRank):

| Rank | Module | PageRank | Domain | Purpose |
|:-----|:-------|:---------|:-------|:--------|
| 1 | `models/marts/customers.sql` | 0.1104 | Models | transforms data from models/marts/orders.sql, models/staging/stg_customers.sql. using CTEs: customer |
| 2 | `models/marts/orders.sql` | 0.0876 | Models | transforms data from models/marts/order_items.sql, models/staging/stg_orders.sql. using CTEs: orders |
| 3 | `models/marts/order_items.sql` | 0.0677 | Models | transforms data from models/staging/stg_orders.sql, models/staging/stg_supplies.sql, models/staging/ |
| 4 | `models/marts/locations.sql` | 0.0359 | Models | transforms data from models/staging/stg_locations.sql. using CTEs: locations. producing a business-f |
| 5 | `models/marts/supplies.sql` | 0.0300 | Models | transforms data from models/staging/stg_supplies.sql. using CTEs: supplies. producing a business-fac |

## Data Sources & Sinks

**Sources (in-degree=0):** 7 data entry points

- `dataset:ecom.raw_customers`
- `dataset:ecom.raw_orders`
- `dataset:ecom.raw_items`
- `dataset:ecom.raw_stores`
- `dataset:ecom.raw_products`
- `dataset:ecom.raw_supplies`
- `transformation:metricflow_time_spine`

**Sinks (out-degree=0):** 5 final outputs

- `dataset:supplies`
- `dataset:products`
- `dataset:customers`
- `dataset:locations`
- `dataset:metricflow_time_spine`

## Known Debt

### Circular Dependencies

None detected. ✅

### Documentation Drift

No discrepancies detected. ✅


## High-Velocity Files

Files changing most frequently (likely pain points or active development):

| File | Velocity (30d) | Last Modified |
|:-----|:--------------:|:--------------|
| `models/staging/stg_orders.sql` | 0.03 | 2026-03-14T12:24:32+03:00 |

## Module Purpose Index

| Module | Language | Domain | Purpose |
|:-------|:---------|:-------|:--------|
| `Taskfile.yml` | yaml | Taskfile.Yml | — |
| `dbt_project.yml` | yaml | Dbt Project.Yml | — |
| `macros/cents_to_dollars.sql` | jinja_sql | Macros | — |
| `macros/generate_schema_name.sql` | jinja_sql | Macros | Module at macros/generate_schema_name.sql (jinja_sql, 23 lines). |
| `models/marts/customers.sql` | jinja_sql | Models | transforms data from models/marts/orders.sql, models/staging/stg_customers.sql. using CTEs: customers, orders, customer_ |
| `models/marts/customers.yml` | yaml | Models | — |
| `models/marts/locations.sql` | jinja_sql | Models | transforms data from models/staging/stg_locations.sql. using CTEs: locations. producing a business-facing mart dataset. |
| `models/marts/locations.yml` | yaml | Models | — |
| `models/marts/metricflow_time_spine.sql` | jinja_sql | Models | — |
| `models/marts/order_items.sql` | jinja_sql | Models | transforms data from models/staging/stg_orders.sql, models/staging/stg_supplies.sql, models/staging/stg_order_items.sql, |
| `models/marts/order_items.yml` | yaml | Models | — |
| `models/marts/orders.sql` | jinja_sql | Models | transforms data from models/marts/order_items.sql, models/staging/stg_orders.sql. using CTEs: orders, order_items, order |
| `models/marts/orders.yml` | yaml | Models | — |
| `models/marts/products.sql` | jinja_sql | Models | transforms data from models/staging/stg_products.sql. using CTEs: products. producing a business-facing mart dataset. |
| `models/marts/products.yml` | yaml | Models | — |
| `models/marts/supplies.sql` | jinja_sql | Models | transforms data from models/staging/stg_supplies.sql. using CTEs: supplies. producing a business-facing mart dataset. |
| `models/marts/supplies.yml` | yaml | Models | — |
| `models/staging/__sources.yml` | yaml | Models | — |
| `models/staging/stg_customers.sql` | jinja_sql | Models | — |
| `models/staging/stg_customers.yml` | yaml | Models | — |
| `models/staging/stg_locations.sql` | jinja_sql | Models | — |
| `models/staging/stg_locations.yml` | yaml | Models | — |
| `models/staging/stg_order_items.sql` | jinja_sql | Models | — |
| `models/staging/stg_order_items.yml` | yaml | Models | — |
| `models/staging/stg_orders.sql` | jinja_sql | Models | Ingests data from source:ecom.raw_orders. using CTEs: source, renamed. staging and normalizing raw data. |
| `models/staging/stg_orders.yml` | yaml | Models | — |
| `models/staging/stg_products.sql` | jinja_sql | Models | Ingests data from source:ecom.raw_products. using CTEs: source, renamed. staging and normalizing raw data. |
| `models/staging/stg_products.yml` | yaml | Models | — |
| `models/staging/stg_supplies.sql` | jinja_sql | Models | Ingests data from source:ecom.raw_supplies. using CTEs: source, renamed. staging and normalizing raw data. |
| `models/staging/stg_supplies.yml` | yaml | Models | — |
| `package-lock.yml` | yaml | Package-Lock.Yml | — |
| `packages.yml` | yaml | Packages.Yml | — |
| `seeds/jaffle-data/raw_customers.csv` | csv | Seeds | — |
| `seeds/jaffle-data/raw_items.csv` | csv | Seeds | — |
| `seeds/jaffle-data/raw_orders.csv` | csv | Seeds | — |
| `seeds/jaffle-data/raw_products.csv` | csv | Seeds | — |
| `seeds/jaffle-data/raw_stores.csv` | csv | Seeds | — |
| `seeds/jaffle-data/raw_supplies.csv` | csv | Seeds | — |

