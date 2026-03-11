import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import diskcache
import tiktoken
from litellm import completion

# We'll import sentence_transformers and sklearn inside the function to avoid slow global imports if not needed
from src.models.schemas import (
    CodebaseGraph,
    ContextWindowBudget,
    DayOneAnswer,
    ModuleNode,
)

logger = logging.getLogger(__name__)


class SemanticistAgent:
    """LLM-powered agent for semantic understanding of the codebase."""

    def __init__(self, repo_root: str, cache_dir: str = ".cartography/cache"):
        self.repo_root = Path(repo_root)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache = diskcache.Cache(str(self.cache_dir))
        self.budget = ContextWindowBudget()
        
        self.prompts_dir = Path(__file__).parent.parent / "prompts"
        
        # Configure models
        self.bulk_model = "openrouter/openai/gpt-4o-mini"
        self.synthesis_model = "openrouter/openai/gpt-4o"
        self.fallback_bulk_model = "openrouter/google/gemini-2.5-flash"
        self.fallback_synthesis_model = "openrouter/anthropic/claude-3.5-sonnet"

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for a text string using cl100k_base."""
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception as e:
            logger.warning(f"Token estimation failed: {e}. Falling back to char count / 4.")
            return len(text) // 4

    def _call_llm(self, prompt: str, task_type: str, response_format: Any = None) -> Any:
        """Helper to call LiteLLM with retries, fallbacks, and budget tracking."""
        model = self.bulk_model if task_type == "bulk" else self.synthesis_model
        fallback = self.fallback_bulk_model if task_type == "bulk" else self.fallback_synthesis_model

        try:
            response = completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                num_retries=3,
                fallbacks=[fallback],
                response_format=response_format,
            )
            
            # Update budget
            usage = response.usage
            if usage:
                if task_type == "bulk":
                    self.budget.bulk_input_tokens += usage.prompt_tokens
                    self.budget.bulk_output_tokens += usage.completion_tokens
                else:
                    self.budget.synthesis_input_tokens += usage.prompt_tokens
                    self.budget.synthesis_output_tokens += usage.completion_tokens
            
            return response
        except Exception as e:
            logger.error(f"LLM call failed for task {task_type}: {e}")
            raise

    def summarize_module(self, module_node: ModuleNode) -> str:
        """Summarize a module for the LLM to save tokens.
        
        Includes AST structure, imports, exported functions, and full SQL queries.
        Omit large function bodies.
        """
        full_path = self.repo_root / module_node.path
        if not full_path.exists():
            return "File not found."

        summary = []
        summary.append(f"Language: {module_node.language}")
        
        if module_node.imports:
            summary.append(f"Imports: {', '.join(module_node.imports)}")
        
        if module_node.public_functions:
            summary.append(f"Public Functions: {', '.join(module_node.public_functions)}")
            
        if module_node.classes:
            summary.append(f"Classes: {', '.join(module_node.classes)}")
            
        # For SQL, include the query itself since it's the core logic
        if module_node.language in ("sql", "jinja_sql") and full_path.exists():
            try:
                content = full_path.read_text(encoding="utf-8")
                # Truncate if insanely large (e.g., > 10k chars)
                if len(content) > 10000:
                    content = content[:10000] + "\n...[TRUNCATED]"
                summary.append(f"SQL Content:\n{content}")
            except Exception:
                pass
                
        return "\n".join(summary)

    def generate_purpose_statement(self, module_node: ModuleNode) -> None:
        """Generate a business purpose statement and detect documentation drift."""
        if not module_node.is_complete_parse or module_node.node_type != "module":
            return
            
        # Hash the summary for caching rather than the raw file
        code_summary = self.summarize_module(module_node)
        content_hash = hashlib.md5(code_summary.encode("utf-8")).hexdigest()
        cache_key = f"purpose_{module_node.path}_{content_hash}"
        
        if cache_key in self.cache:
            module_node.purpose_statement = self.cache[cache_key]
            return

        prompt_template = (self.prompts_dir / "purpose_prompt.txt").read_text(encoding="utf-8")
        prompt = prompt_template.format(module_path=module_node.path, code_summary=code_summary)

        try:
            response = self._call_llm(prompt, task_type="bulk")
            purpose = response.choices[0].message.content.strip()
            
            module_node.purpose_statement = purpose
            self.cache[cache_key] = purpose
            
            # Basic doc drift check: If we had to rely heavily on the LLM vs existing docstring
            # A more advanced version would ask the LLM specifically to compare them.
            # For now, we'll mark True if the LLM generated something substantial.
            module_node.doc_drift = bool(purpose and len(purpose) > 20)
            
        except Exception as e:
            logger.warning(f"Failed to generate purpose for {module_node.path}: {e}")

    def cluster_into_domains(self, modules: List[ModuleNode]) -> None:
        """Cluster modules into business domains using Sentence Transformers and K-Means."""
        try:
            from sentence_transformers import SentenceTransformer
            from sklearn.cluster import KMeans
        except ImportError as e:
            logger.error(f"Failed to import clustering dependencies: {e}")
            return

        valid_modules = [m for m in modules if m.purpose_statement]
        if not valid_modules:
            return

        statements = [m.purpose_statement for m in valid_modules]
        
        # Determine dynamic K
        k = max(2, min(int(math.sqrt(len(valid_modules))), 15))
        if len(valid_modules) < k:
            k = len(valid_modules)

        logger.info(f"Clustering {len(valid_modules)} modules into {k} domains.")

        # Load embedding model
        model_name = "all-MiniLM-L6-v2"
        embedder = SentenceTransformer(model_name)
        embeddings = embedder.encode(statements)

        # Storage with versioning
        emb_path = self.repo_root / f".cartography/embeddings_{model_name}.pkl"
        try:
            import pickle
            with open(emb_path, "wb") as f:
                pickle.dump(embeddings, f)
        except Exception as e:
            logger.warning(f"Failed to save embeddings: {e}")

        # K-Means clustering
        kmeans = KMeans(n_clusters=k, random_state=42, n_init="auto")
        labels = kmeans.fit_predict(embeddings)

        # Group statements by cluster
        clusters: Dict[int, List[str]] = {i: [] for i in range(k)}
        for label, statement in zip(labels, statements):
            clusters[label].append(statement)

        # Label each cluster using LLM
        domain_labels: Dict[int, str] = {}
        prompt_template = (self.prompts_dir / "domain_label_prompt.txt").read_text(encoding="utf-8")

        for cluster_id, stmts in clusters.items():
            cluster_text = "\n- ".join(stmts[:10]) # Limit to top 10 for prompt
            prompt = prompt_template.format(cluster_statements=cluster_text)
            try:
                response = self._call_llm(prompt, task_type="synthesis")
                label = response.choices[0].message.content.strip()
                domain_labels[cluster_id] = label
            except Exception:
                domain_labels[cluster_id] = f"Domain_{cluster_id}"

        # Assign back to modules
        for m, label_id in zip(valid_modules, labels):
            m.domain_cluster = domain_labels[label_id]

    def answer_day_one_questions(self, graph: CodebaseGraph) -> List[DayOneAnswer]:
        """Answer the Five FDE Questions using structured output."""
        prompt_template = (self.prompts_dir / "day_one_questions.txt").read_text(encoding="utf-8")
        
        # Build graph summary
        summary = []
        summary.append(f"Total Modules: {len(graph.modules)}")
        
        top_hubs = sorted(graph.modules, key=lambda m: m.pagerank, reverse=True)[:10]
        summary.append(f"Top 10 Hubs (PageRank): {', '.join(m.path for m in top_hubs)}")
        
        high_velocity = sorted(graph.modules, key=lambda m: m.change_velocity_30d, reverse=True)[:10]
        summary.append(f"High Velocity Modules: {', '.join(m.path for m in high_velocity)}")
        
        sources = [d.name for d in graph.datasets if d.is_source_of_truth]
        summary.append(f"Source Datasets: {', '.join(sources)}")
        
        prompt = prompt_template.format(graph_summary="\n".join(summary))

        # Enforce JSON Schema Output using Pydantic via LiteLLM structured outputs
        # Note: LiteLLM supports response_format for OpenAI models. 
        # Structure is defined as a list of DayOneAnswer.
        
        # Create a pydantic model for the response wrapper since we expect a list
        from pydantic import BaseModel
        class DayOneResponse(BaseModel):
            answers: List[DayOneAnswer]

        try:
            response = self._call_llm(
                prompt, 
                task_type="synthesis", 
                response_format=DayOneResponse
            )
            
            # The parsed response object is attached by LiteLLM if model supports it
            # fallback: attempt json.loads
            content = response.choices[0].message.content
            if hasattr(response.choices[0].message, "parsed") and response.choices[0].message.parsed:
                return response.choices[0].message.parsed.answers
            elif isinstance(content, str):
                # Clean markdown backticks if present
                clean_content = content.replace("```json", "").replace("```", "").strip()
                data = json.loads(clean_content)
                if isinstance(data, dict) and "answers" in data:
                    return [DayOneAnswer(**a) for a in data["answers"]]
                elif isinstance(data, list):
                    return [DayOneAnswer(**a) for a in data]
            return []
            
        except Exception as e:
            logger.error(f"Failed to answer Day One Questions: {e}")
            logger.error(f"Raw content was: {content if 'content' in locals() else 'N/A'}")
            return []

    def run(self, graph: CodebaseGraph) -> None:
        """Run the full Semanticist pipeline on the graph."""
        logger.info("Semanticist: Generating purpose statements.")
        for module in graph.modules:
            self.generate_purpose_statement(module)
            
        logger.info("Semanticist: Clustering domains.")
        self.cluster_into_domains(graph.modules)
        
        logger.info("Semanticist: Budget so far "
                    f"Inputs: Bulk={self.budget.bulk_input_tokens}, Synth={self.budget.synthesis_input_tokens}. "
                    f"Outputs: Bulk={self.budget.bulk_output_tokens}, Synth={self.budget.synthesis_output_tokens}.")
