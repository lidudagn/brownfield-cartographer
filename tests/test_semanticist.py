import pytest
from unittest.mock import MagicMock, patch

from src.agents.semanticist import SemanticistAgent
from src.models.schemas import CodebaseGraph, ModuleNode, DayOneAnswer


@pytest.fixture
def semanticist(tmp_path):
    # Use tmp_path for cache so we don't pollute local directories
    return SemanticistAgent(repo_root=str(tmp_path), cache_dir=str(tmp_path / "cache"))


def test_context_window_budget(semanticist):
    """Test token estimation and budget tracking limits."""
    text = "def hello_world(): return True"
    tokens = semanticist.estimate_tokens(text)
    assert tokens > 0, "Token estimation should return > 0 for non-empty text."

    # Model selection checks
    assert semanticist.bulk_model == "openrouter/openai/gpt-4o-mini"
    assert semanticist.synthesis_model == "openrouter/openai/gpt-4o"


@patch("src.agents.semanticist.completion")
@patch.object(SemanticistAgent, "_extract_existing_docs")
def test_doc_drift_detection(mock_extract_docs, mock_completion, semanticist):
    """Test doc drift flags correctly setting based on LLM response."""
    # Mock existing docs so the drift check isn't skipped
    mock_extract_docs.return_value = "This module does one thing."
    
    # Mock LLM responses for bulk purpose generation and then drift check
    mock_msg1 = MagicMock()
    mock_msg1.content = "This module handles database ingestion and API fetching."
    mock_choice1 = MagicMock()
    mock_choice1.message = mock_msg1
    mock_res1 = MagicMock()
    mock_res1.choices = [mock_choice1]
    mock_res1.usage.prompt_tokens = 10
    mock_res1.usage.completion_tokens = 20
    
    mock_msg2 = MagicMock()
    mock_msg2.content = "Analysis: The docs say X but purpose says Y. DRIFT: true."
    mock_choice2 = MagicMock()
    mock_choice2.message = mock_msg2
    mock_res2 = MagicMock()
    mock_res2.choices = [mock_choice2]
    mock_res2.usage.prompt_tokens = 50
    mock_res2.usage.completion_tokens = 20
    
    mock_completion.side_effect = [mock_res1, mock_res2]
    
    node = ModuleNode(
        path="src/ingest.py", 
        language="python", 
        is_complete_parse=True,
    )
    
    # Need mock prompts
    from pathlib import Path
    semanticist.prompts_dir.mkdir(parents=True, exist_ok=True)
    (semanticist.prompts_dir / "purpose_prompt.txt").write_text("{module_path} {code_summary}", encoding="utf-8")
    (semanticist.prompts_dir / "doc_drift_prompt.txt").write_text("Compare {existing_docs} vs {inferred_purpose}", encoding="utf-8")
    
    semanticist.generate_purpose_statement(node)
    
    # Assert Purpose is set and doc_drift is flagged
    assert node.purpose_statement == mock_choice1.message.content
    assert node.doc_drift is True


@patch("src.agents.semanticist.completion")
def test_day_one_questions_structured_output(mock_completion, semanticist):
    """Verify that structured output works from the LLM response."""
    # Mocking the structured output parsing
    node1 = ModuleNode(path="main.py", language="python", pagerank=0.9)
    node2 = ModuleNode(path="db.py", language="python", pagerank=0.5)
    
    graph = CodebaseGraph(
        repo_path="test",
        analysis_timestamp="2024",
        modules=[node1, node2],
    )
    
    # Setup mock parsed Pydantic response
    mock_msg = MagicMock()
    mock_msg.parsed.answers = [
        DayOneAnswer(
            question="What is the primary data ingestion path?",
            answer="main.py reads from an API.",
            evidence=[]
        )
    ]
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_res = MagicMock()
    mock_res.choices = [mock_choice]
    mock_res.usage = None  # don't care about usage tracking here
    
    mock_completion.return_value = mock_res
    
    answers = semanticist.answer_day_one_questions(graph)
    
    assert len(answers) == 1
    assert answers[0].question == "What is the primary data ingestion path?"
    assert "main.py" in answers[0].answer
