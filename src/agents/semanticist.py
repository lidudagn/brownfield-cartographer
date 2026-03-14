import hashlib
import json
import logging
import math
import os
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
        
        # Configure models — override via env vars for local LLM (e.g. Ollama)
        self.bulk_model = os.environ.get("CARTOGRAPHER_BULK_MODEL", "openrouter/openai/gpt-4o-mini")
        self.synthesis_model = os.environ.get("CARTOGRAPHER_SYNTH_MODEL", "openrouter/openai/gpt-4o")
        self.fallback_bulk_model = os.environ.get("CARTOGRAPHER_FALLBACK_BULK", "openrouter/google/gemini-2.5-flash")
        self.fallback_synthesis_model = os.environ.get("CARTOGRAPHER_FALLBACK_SYNTH", "openrouter/anthropic/claude-3.5-sonnet")

    def estimate_tokens(self, text: str) -> int:
        """Estimate token count for a text string using cl100k_base."""
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception as e:
            logger.warning(f"Token estimation failed: {e}. Falling back to char count / 4.")
            return len(text) // 4

    # Approximate per-token pricing (USD per 1M tokens) for cost estimation
    _PRICING = {
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
        "claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
    }

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate USD cost based on model and token counts."""
        # Extract base model name from the full model path
        base = model.rsplit("/", 1)[-1] if "/" in model else model
        pricing = self._PRICING.get(base, {"input": 0.15, "output": 0.60})
        cost = (input_tokens * pricing["input"] / 1_000_000) + (output_tokens * pricing["output"] / 1_000_000)
        return cost

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
                # Calculate real cost
                self.budget.estimated_cost_usd += self._estimate_cost(
                    model, usage.prompt_tokens, usage.completion_tokens
                )
            
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

    def _extract_existing_docs(self, module_node: ModuleNode) -> str:
        """Extract existing docstrings and leading comments from a module."""
        full_path = self.repo_root / module_node.path
        if not full_path.exists():
            return ""
        try:
            content = full_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return ""

        docs = []
        if module_node.language == "python":
            # Extract module-level docstring and leading comments
            import ast
            try:
                tree = ast.parse(content)
                ds = ast.get_docstring(tree)
                if ds:
                    docs.append(ds)
            except SyntaxError:
                pass
            # Also grab leading comment lines
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    docs.append(stripped.lstrip("# "))
                elif stripped and not stripped.startswith(('"', "'", "import", "from")):
                    break
        elif module_node.language in ("sql", "jinja_sql"):
            # Extract SQL comment headers (-- and /* */ blocks)
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("--"):
                    docs.append(stripped.lstrip("- "))
                elif stripped and not stripped.startswith("{{"):
                    break
        elif module_node.language == "yaml":
            # Extract YAML comment headers
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("#"):
                    docs.append(stripped.lstrip("# "))
                elif stripped:
                    break

        return "\n".join(docs).strip()

    def _detect_doc_drift(self, module_node: ModuleNode, purpose: str) -> bool:
        """Detect doc drift by comparing existing docs against LLM-inferred purpose."""
        existing_docs = self._extract_existing_docs(module_node)
        if not existing_docs:
            return False  # No existing docs to contradict

        drift_prompt_path = self.prompts_dir / "doc_drift_prompt.txt"
        if not drift_prompt_path.exists():
            return False

        prompt_template = drift_prompt_path.read_text(encoding="utf-8")
        prompt = prompt_template.format(
            module_path=module_node.path,
            existing_docs=existing_docs,
            inferred_purpose=purpose,
        )

        try:
            response = self._call_llm(prompt, task_type="bulk")
            result = response.choices[0].message.content.strip().lower()
            return "drift: true" in result
        except Exception as e:
            logger.warning(f"Doc drift LLM check failed for {module_node.path}: {e}")
            return False

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
            
            # Real doc drift: compare existing docstring vs LLM-inferred purpose
            module_node.doc_drift = self._detect_doc_drift(module_node, purpose)
            
        except Exception as e:
            logger.warning(f"Failed to generate purpose for {module_node.path}: {e}")

    def _infer_domain_from_path(self, module_path: str) -> str:
        """Infer a domain label from the file path when clustering is unavailable."""
        parts = Path(module_path).parts
        # Use the first meaningful directory as the domain
        for part in parts:
            if part in (".", "..", "src", "lib", "app"):
                continue
            return part.replace("_", " ").title()
        return Path(module_path).stem.replace("_", " ").title()

    def cluster_into_domains(self, modules: List[ModuleNode]) -> None:
        """Cluster modules into business domains using Sentence Transformers and K-Means."""
        try:
            from sentence_transformers import SentenceTransformer
            from sklearn.cluster import KMeans
        except ImportError as e:
            logger.warning(f"Clustering deps unavailable ({e}). Falling back to path-based domains.")
            # Fallback: assign domain from directory structure
            for m in modules:
                if not m.domain_cluster:
                    m.domain_cluster = self._infer_domain_from_path(m.path)
            return

        valid_modules = [m for m in modules if m.purpose_statement]
        if not valid_modules:
            # Fallback for empty purpose statements
            for m in modules:
                if not m.domain_cluster:
                    m.domain_cluster = self._infer_domain_from_path(m.path)
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
        cluster_modules: Dict[int, List[ModuleNode]] = {i: [] for i in range(k)}
        for label, (statement, mod) in zip(labels, zip(statements, valid_modules)):
            clusters[label].append(statement)
            cluster_modules[label].append(mod)

        # Label each cluster using LLM
        domain_labels: Dict[int, str] = {}
        prompt_template = (self.prompts_dir / "domain_label_prompt.txt").read_text(encoding="utf-8")

        for cluster_id, stmts in clusters.items():
            cluster_text = "\n- ".join(stmts[:10]) # Limit to top 10 for prompt
            prompt = prompt_template.format(cluster_statements=cluster_text)
            try:
                response = self._call_llm(prompt, task_type="synthesis")
                label = response.choices[0].message.content.strip()
                # Reject generic/empty labels
                if label and label.lower() not in ("uncategorized", "other", "general", ""):
                    domain_labels[cluster_id] = label
                else:
                    # Derive label from the most common directory among cluster members
                    dirs = [str(Path(m.path).parent) for m in cluster_modules[cluster_id]]
                    most_common = max(set(dirs), key=dirs.count) if dirs else "General"
                    domain_labels[cluster_id] = most_common.replace("/", " > ").replace("_", " ").title()
            except Exception:
                dirs = [str(Path(m.path).parent) for m in cluster_modules[cluster_id]]
                most_common = max(set(dirs), key=dirs.count) if dirs else f"Domain_{cluster_id}"
                domain_labels[cluster_id] = most_common.replace("/", " > ").replace("_", " ").title()

        # Assign back to modules
        for m, label_id in zip(valid_modules, labels):
            m.domain_cluster = domain_labels[label_id]

        # Assign path-based labels to any modules that weren't clustered
        for m in modules:
            if not m.domain_cluster:
                m.domain_cluster = self._infer_domain_from_path(m.path)

    def answer_day_one_questions(self, graph: CodebaseGraph) -> List[DayOneAnswer]:
        """Answer the Five FDE Questions using structured output.

        Feeds the FULL Surveyor + Hydrologist output to give the LLM
        maximum context for answering.
        """
        prompt_template = (self.prompts_dir / "day_one_questions.txt").read_text(encoding="utf-8")
        
        # Build comprehensive graph summary with full Surveyor + Hydrologist data
        summary = []
        summary.append(f"Total Modules: {len(graph.modules)}")
        summary.append(f"Total Datasets: {len(graph.datasets)}")
        summary.append(f"Total Transformations: {len(graph.transformations)}")
        summary.append(f"Import Edges: {len(graph.imports_edges)}, Calls: {len(graph.calls_edges)}")
        summary.append(f"Produces: {len(graph.produces_edges)}, Consumes: {len(graph.consumes_edges)}")
        
        # Top hubs by PageRank with details
        top_hubs = sorted(graph.modules, key=lambda m: m.pagerank, reverse=True)[:10]
        summary.append("\nTop 10 Critical Modules (by PageRank):")
        for m in top_hubs:
            summary.append(f"  - {m.path} (PageRank={m.pagerank:.4f}, velocity={m.change_velocity_30d:.2f}, lang={m.language})")
            if m.purpose_statement:
                summary.append(f"    Purpose: {m.purpose_statement[:200]}")
        
        # High velocity files
        high_velocity = sorted(graph.modules, key=lambda m: m.change_velocity_30d, reverse=True)[:10]
        summary.append("\nHigh Velocity Modules (most frequently changed):")
        for m in high_velocity:
            summary.append(f"  - {m.path} (velocity={m.change_velocity_30d:.2f})")
        
        # Data sources and sinks
        summary.append("\nDatasets:")
        for d in graph.datasets:
            summary.append(f"  - {d.name} (type={d.storage_type}, source_of_truth={d.is_source_of_truth})")
        
        # Transformations with lineage
        summary.append("\nTransformations:")
        for t in graph.transformations:
            summary.append(f"  - {t.name} ({t.source_file}): reads {t.source_datasets} → writes {t.target_datasets}")
        
        # Entry points
        entry_points = [m for m in graph.modules if m.is_entry_point]
        if entry_points:
            summary.append("\nEntry Points:")
            for ep in entry_points:
                summary.append(f"  - {ep.path} (type={ep.entry_point_type})")
        
        # Dead code and circular deps
        if graph.dead_code_candidates:
            summary.append(f"\nDead Code Candidates: {len(graph.dead_code_candidates)}")
            for dc in graph.dead_code_candidates[:5]:
                summary.append(f"  - {dc.module_path} (confidence={dc.confidence:.0%})")
        if graph.circular_dependencies:
            summary.append(f"\nCircular Dependencies: {len(graph.circular_dependencies)}")
        
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
        logger.info("Semanticist: Generating purpose statements (top 100 modules).")
        # Prioritize top 100 modules by PageRank to keep demonstration fast and focused
        top_modules = sorted(graph.modules, key=lambda m: getattr(m, 'pagerank', 0), reverse=True)[:100]
        for module in top_modules:
            self.generate_purpose_statement(module)
            
        logger.info("Semanticist: Clustering domains.")
        self.cluster_into_domains(graph.modules)
        
        logger.info("Semanticist: Budget so far "
                    f"Inputs: Bulk={self.budget.bulk_input_tokens}, Synth={self.budget.synthesis_input_tokens}. "
                    f"Outputs: Bulk={self.budget.bulk_output_tokens}, Synth={self.budget.synthesis_output_tokens}.")

        # After the LLM pass, generate fallback purpose for critical modules still missing one
        for mod in sorted(graph.modules, key=lambda m: getattr(m, 'pagerank', 0), reverse=True)[:10]:
            if not mod.purpose_statement:
                mod.purpose_statement = self._generate_fallback_purpose(mod)

    def _generate_fallback_purpose(self, mod: ModuleNode) -> str:
        """Generate a static-analysis-based purpose statement when LLM fails."""
        parts = []
        if mod.language == "jinja_sql":
            if mod.imports:
                refs = [i for i in mod.imports if not i.startswith("source:")]
                sources = [i for i in mod.imports if i.startswith("source:")]
                if sources:
                    parts.append(f"Ingests data from {', '.join(sources)}")
                if refs:
                    parts.append(f"transforms data from {', '.join(refs)}")
            if mod.cte_definitions:
                parts.append(f"using CTEs: {', '.join(mod.cte_definitions)}")
            if "marts" in mod.path:
                parts.append("producing a business-facing mart dataset")
            elif "staging" in mod.path:
                parts.append("staging and normalizing raw data")
        elif mod.language == "python":
            if mod.public_functions:
                parts.append(f"Exposes {len(mod.public_functions)} functions: {', '.join(mod.public_functions[:5])}")
            if mod.classes:
                parts.append(f"Defines classes: {', '.join(mod.classes[:3])}")
        elif mod.language in ("typescript", "tsx", "javascript"):
            if mod.public_functions:
                parts.append(f"Exposes {len(mod.public_functions)} functions/methods: {', '.join(mod.public_functions[:5])}")
            if mod.classes:
                parts.append(f"Defines classes: {', '.join(mod.classes[:3])}")
            if mod.imports:
                parts.append(f"Imports from {len(mod.imports)} modules")
        
        return ". ".join(parts) + "." if parts else f"Module at {mod.path} ({mod.language}, {mod.lines_of_code} lines)."
