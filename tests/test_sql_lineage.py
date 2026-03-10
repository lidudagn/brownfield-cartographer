"""
Tests for sqlglot parsing, column lineage, and dbt dialect auto-detection.
"""

from src.analyzers.sql_lineage import (
    preprocess_dbt_sql,
    extract_column_lineage,
    extract_sql_dependencies,
    detect_dialect,
)

def test_preprocess_dbt_sql():
    """Verify Jinja preprocessing and evidence extraction."""
    raw_sql = """
    with source as (
        select * from {{ source('jaffle_shop', 'raw_customers') }}
    ),
    renamed as (
        select
            id as customer_id,
            first_name,
            last_name
        from source
    )
    select * from renamed left join {{ ref('stg_orders') }} using (customer_id)
    """
    
    clean_sql, ref_evidences, src_evidences, unresolved = preprocess_dbt_sql(
        raw_sql, "models/customers.sql"
    )
    
    assert "source('jaffle_shop', 'raw_customers')" in src_evidences[0].snippet
    assert "ref('stg_orders')" in ref_evidences[0].snippet
    assert "__dbt_source__jaffle_shop__raw_customers" in clean_sql
    assert "__dbt_ref__stg_orders" in clean_sql
    assert len(unresolved) == 0


def test_extract_column_lineage():
    """Verify target vs source columns and transformation categorizations."""
    sql = """
    select 
        c.customer_id, 
        sum(o.subtotal) as total_spent,
        count(o.order_id) as num_orders,
        'Active' as status
    from customers c
    left join orders o on c.customer_id = o.customer_id
    group by 1
    """
    
    lineage = extract_column_lineage(sql, "test.sql", "postgres")
    
    assert len(lineage) == 4
    
    # customer_id -> passthrough
    c_id = next(l for l in lineage if l.target_column == "customer_id")
    assert "c.customer_id" in c_id.source_columns
    assert c_id.transformation == "passthrough"
    
    # total_spent -> aggregate
    t_spent = next(l for l in lineage if l.target_column == "total_spent")
    assert "o.subtotal" in t_spent.source_columns
    assert t_spent.transformation == "aggregate"
    
    # num_orders -> aggregate
    n_ord = next(l for l in lineage if l.target_column == "num_orders")
    assert "o.order_id" in n_ord.source_columns
    assert n_ord.transformation == "aggregate"
    
    # status -> compute (or rename of a literal)
    status = next(l for l in lineage if l.target_column == "status")
    assert len(status.source_columns) == 0


def test_full_sql_extraction_deps():
    """Verify that the full pipeline gets the right deps."""
    raw_sql = """
    select * from {{ ref('stg_customers') }}
    inner join {{ ref('stg_orders') }} using (id)
    """
    
    deps, lineage, evs, unres = extract_sql_dependencies(raw_sql, "test.sql", "postgres")
    assert "stg_customers" in deps
    assert "stg_orders" in deps
