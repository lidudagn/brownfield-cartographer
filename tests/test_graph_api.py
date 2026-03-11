import pytest
from src.agents.hydrologist import Hydrologist
from src.models.schemas import CodebaseGraph, DatasetNode, TransformationNode, ConsumesEdge, ProducesEdge, Evidence

@pytest.fixture
def mock_codebase_graph():
    datasets = [
        DatasetNode(node_id="dataset:A", name="A", storage_type="table"),
        DatasetNode(node_id="dataset:B", name="B", storage_type="table"),
        DatasetNode(node_id="dataset:C", name="C", storage_type="table"),
        DatasetNode(node_id="dataset:D", name="D", storage_type="table")
    ]
    transformations = [
        TransformationNode(node_id="transformation:T1", name="T1", source_datasets=["dataset:A"], target_datasets=["dataset:B"], transformation_type="select", source_file="t1.sql", line_range=(1, 1), column_lineage=[]),
        TransformationNode(node_id="transformation:T2", name="T2", source_datasets=["dataset:B"], target_datasets=["dataset:C"], transformation_type="select", source_file="t2.sql", line_range=(1, 1), column_lineage=[]),
        TransformationNode(node_id="transformation:T3", name="T3", source_datasets=["dataset:C"], target_datasets=["dataset:D"], transformation_type="select", source_file="t3.sql", line_range=(1, 1), column_lineage=[])
    ]
    
    # Lineage A -> T1 -> B -> T2 -> C -> T3 -> D
    ev = Evidence(file_path="test", line_start=1, line_end=1, snippet="", analysis_method="regex")
    consumes_edges = [
        ConsumesEdge(source="transformation:T1", target="dataset:A", evidence=ev),
        ConsumesEdge(source="transformation:T2", target="dataset:B", evidence=ev),
        ConsumesEdge(source="transformation:T3", target="dataset:C", evidence=ev)
    ]
    produces_edges = [
        ProducesEdge(source="transformation:T1", target="dataset:B", evidence=ev),
        ProducesEdge(source="transformation:T2", target="dataset:C", evidence=ev),
        ProducesEdge(source="transformation:T3", target="dataset:D", evidence=ev)
    ]
    
    return CodebaseGraph(
        repo_path="/test",
        analysis_timestamp="2024",
        modules=[],
        datasets=datasets,
        transformations=transformations,
        imports_edges=[],
        calls_edges=[],
        consumes_edges=consumes_edges,
        produces_edges=produces_edges,
        dead_code_candidates=[],
        circular_dependencies=[],
        analysis_errors=[]
    )

def test_build_lineage_graph(mock_codebase_graph):
    hydro = Hydrologist()
    graph = hydro.build_lineage_graph(mock_codebase_graph)
    
    assert graph.number_of_nodes() == 7  # 4 datasets + 3 transformations
    assert graph.number_of_edges() == 6
    assert graph.has_edge("dataset:A", "transformation:T1")
    assert graph.has_edge("transformation:T1", "dataset:B")

def test_blast_radius(mock_codebase_graph):
    hydro = Hydrologist()
    hydro.build_lineage_graph(mock_codebase_graph)
    
    # Downstream from A
    radii = hydro.blast_radius("dataset:A", direction="downstream")
    assert radii["transformation:T1"] == 1
    assert radii["dataset:B"] == 1
    assert radii["transformation:T2"] == 1
    assert radii["dataset:C"] == 1
    
    # Upstream from C
    up_radii = hydro.blast_radius("dataset:C", direction="upstream")
    assert up_radii["transformation:T2"] == 1
    assert up_radii["dataset:B"] == 1
    assert up_radii["transformation:T1"] == 1
    assert up_radii["dataset:A"] == 1

def test_trace_lineage(mock_codebase_graph):
    hydro = Hydrologist()
    hydro.build_lineage_graph(mock_codebase_graph)
    
    paths = hydro.trace_lineage("dataset:A", "dataset:C")
    assert len(paths) == 1
    assert paths[0] == ["dataset:A", "transformation:T1", "dataset:B", "transformation:T2", "dataset:C"]

def test_detect_cycles(mock_codebase_graph):
    hydro = Hydrologist()
    graph = hydro.build_lineage_graph(mock_codebase_graph)
    
    # Initially no cycles
    cycles = hydro.detect_cycles()
    assert len(cycles) == 0
    
    # Add a cycle: T3 targets A
    graph.add_edge("transformation:T3", "dataset:A")
    cycles = hydro.detect_cycles()
    assert len(cycles) == 1
    assert "dataset:A" in cycles[0]
    assert "transformation:T3" in cycles[0]

def test_get_statistics(mock_codebase_graph):
    hydro = Hydrologist()
    hydro.build_lineage_graph(mock_codebase_graph)
    
    stats = hydro.get_statistics()
    assert stats["num_datasets"] == 4
    assert stats["num_transformations"] == 3
    assert stats["num_edges"] == 6
    assert stats["max_lineage_depth"] == 6 # A->T1->B->T2->C->T3->D is length 6 edges
