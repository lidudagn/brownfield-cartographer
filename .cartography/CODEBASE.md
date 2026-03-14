# CODEBASE.md — Living Architectural Context
**Generated:** 2026-03-14T12:26:26.155382
**Repository:** `/home/lidya/Videos/week 4/brownfield-cartographer/../jaffle-shop`

## Architecture Overview

This codebase contains **38 modules** (17 yaml, 15 jinja_sql, 6 csv) totaling **155,093 lines of code**. It is organized into 1 inferred domains: uncategorized (38). There are **13 entry points** and **13 data transformations** tracked.

## Critical Path

The most architecturally significant modules (by PageRank):

| Rank | Module | PageRank | Domain | Purpose |
|:-----|:-------|:---------|:-------|:--------|
| 1 | `models/marts/customers.sql` | 0.1104 | — | The module serves to aggregate and summarize customer-related data by combining detailed customer in |
| 2 | `models/marts/orders.sql` | 0.0876 | — | The module serves to aggregate and summarize order data, providing insights into the costs, item cou |
| 3 | `models/marts/order_items.sql` | 0.0677 | — | The module `models/marts/order_items.sql` serves the business function of aggregating and enhancing  |
| 4 | `models/marts/locations.sql` | 0.0359 | — | This module serves as the primary and definitive source for cleaned location data within the busines |
| 5 | `models/marts/supplies.sql` | 0.0300 | — | The module at `models/marts/supplies.sql` serves to transform and organize supply data from a stagin |

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
- `dataset:metricflow_time_spine`
- `dataset:products`
- `dataset:locations`
- `dataset:customers`

## Known Debt

### Circular Dependencies

None detected. ✅

### Documentation Drift (2 files)

Modules where the implementation contradicts the docstring:

- `models/marts/order_items.sql`
- `models/staging/__sources.yml`


## High-Velocity Files

Files changing most frequently (likely pain points or active development):

No files changed in the last 30 days (archived/stable repository).

**Most recently modified:**

- `packages.yml` — 2026-01-20T15:38:12+00:00
- `models/marts/locations.yml` — 2025-07-01T08:58:01-05:00
- `models/marts/order_items.yml` — 2025-07-01T08:58:01-05:00
- `models/marts/customers.yml` — 2025-07-01T08:58:01-05:00
- `seeds/jaffle-data/raw_orders.csv` — 2025-06-19T09:03:40+12:00

## Module Purpose Index

| Module | Language | Domain | Purpose |
|:-------|:---------|:-------|:--------|
| `Taskfile.yml` | yaml | — | The Taskfile.yml module serves as a configuration file that defines automated tasks and workflows for the development an |
| `dbt_project.yml` | yaml | — | The `dbt_project.yml` module serves as a configuration file for a dbt (data build tool) project, defining the project's  |
| `macros/cents_to_dollars.sql` | jinja_sql | — | The `cents_to_dollars` module serves the business function of standardizing the conversion of monetary values from cents |
| `macros/generate_schema_name.sql` | jinja_sql | — | This module's business purpose is to dynamically determine the database schema where data models and seeds are materiali |
| `models/marts/customers.sql` | jinja_sql | — | The module serves to aggregate and summarize customer-related data by combining detailed customer information with their |
| `models/marts/customers.yml` | yaml | — | The `models/marts/customers.yml` module serves to define and structure customer-related data, likely aggregating and tra |
| `models/marts/locations.sql` | jinja_sql | — | This module serves as the primary and definitive source for cleaned location data within the business intelligence layer |
| `models/marts/locations.yml` | yaml | — | The module located at `models/marts/locations.yml` serves the business function of defining and organizing location-rela |
| `models/marts/metricflow_time_spine.sql` | jinja_sql | — | The `metricflow_time_spine.sql` module creates a time dimension table that generates a sequence of daily dates for a ten |
| `models/marts/order_items.sql` | jinja_sql | — | The module `models/marts/order_items.sql` serves the business function of aggregating and enhancing order item data by i |
| `models/marts/order_items.yml` | yaml | — | The `order_items` module serves to define and manage the data structure and configuration pertaining to individual items |
| `models/marts/orders.sql` | jinja_sql | — | The module serves to aggregate and summarize order data, providing insights into the costs, item counts, and types of pr |
| `models/marts/orders.yml` | yaml | — | The module defines the structure and schema for order-related data within the business's data mart, serving as a foundat |
| `models/marts/products.sql` | jinja_sql | — | This module serves as the definitive business-ready view of product information, making clean product data directly avai |
| `models/marts/products.yml` | yaml | — | The module at `models/marts/products.yml` serves to define and structure the data related to product offerings within th |
| `models/marts/supplies.sql` | jinja_sql | — | The module at `models/marts/supplies.sql` serves to transform and organize supply data from a staging table into a struc |
| `models/marts/supplies.yml` | yaml | — | The module at `models/marts/supplies.yml` serves to manage and define the supply-related data entities within a business |
| `models/staging/__sources.yml` | yaml | — | The module `__sources.yml` serves the business function of aggregating and defining various raw data sources related to  |
| `models/staging/stg_customers.sql` | jinja_sql | — | This module serves to ingest raw customer data from the e-commerce source and prepare it for further analytical processi |
| `models/staging/stg_customers.yml` | yaml | — | The module `stg_customers.yml` serves the business purpose of defining and managing customer data in a staging environme |
| `models/staging/stg_locations.sql` | jinja_sql | — | The `stg_locations` module serves to transform and prepare store location data from the raw source, simplifying it by re |
| `models/staging/stg_locations.yml` | yaml | — | The `stg_locations` module serves the business purpose of defining and managing the staging data related to geographic l |
| `models/staging/stg_order_items.sql` | jinja_sql | — | The `stg_order_items` module serves to transform and stage raw order item data from the e-commerce system for further an |
| `models/staging/stg_order_items.yml` | yaml | — | The module `stg_order_items.yml` is designed to define the structure and configuration for staging order items, which li |
| `models/staging/stg_orders.sql` | jinja_sql | — | — |
| `models/staging/stg_orders.yml` | yaml | — | The `stg_orders` module is likely responsible for managing and staging order data within the application's data pipeline |
| `models/staging/stg_products.sql` | jinja_sql | — | The purpose of the `stg_products` module is to transform raw product data from the e-commerce platform into a structured |
| `models/staging/stg_products.yml` | yaml | — | The `stg_products` module serves as a staging area for managing product data within the system, organizing and transform |
| `models/staging/stg_supplies.sql` | jinja_sql | — | The module serves the business function of transforming and structuring raw supply data into a standardized format for f |
| `models/staging/stg_supplies.yml` | yaml | — | The module `stg_supplies.yml` appears to serve as a staging area for managing supply-related data within the system. It  |
| `package-lock.yml` | yaml | — | The `package-lock.yml` module serves to manage and maintain the consistency of package dependencies within a software pr |
| `packages.yml` | yaml | — | This module defines the external dependencies or software packages required by the codebase, specifying their versions a |
| `seeds/jaffle-data/raw_customers.csv` | csv | — | The `raw_customers.csv` module serves the business function of providing a foundational dataset that likely contains ess |
| `seeds/jaffle-data/raw_items.csv` | csv | — | The module `seeds/jaffle-data/raw_items.csv` serves as a data source that likely contains raw item information, possibly |
| `seeds/jaffle-data/raw_orders.csv` | csv | — | The `raw_orders.csv` module serves the purpose of providing a comprehensive dataset of customer orders, capturing transa |
| `seeds/jaffle-data/raw_products.csv` | csv | — | The module 'raw_products.csv' serves as a data repository for storing information related to products, likely as part of |
| `seeds/jaffle-data/raw_stores.csv` | csv | — | The module at `seeds/jaffle-data/raw_stores.csv` serves the business purpose of providing a foundational dataset that co |
| `seeds/jaffle-data/raw_supplies.csv` | csv | — | The `raw_supplies.csv` module serves as a foundational data source for tracking the inventory of raw materials used in p |

