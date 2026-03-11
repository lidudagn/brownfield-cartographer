"""
Tree-sitter multi-language AST analyzer with LanguageRouter.

Provides structural code understanding for Python, SQL, YAML via tree-sitter
S-expression queries. Extracts imports, functions, classes, complexity metrics,
and evidence-linked findings.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from src.models.schemas import (
    AnalysisError,
    Evidence,
    ModuleNode,
    UnresolvedReference,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Language Router (M-1)
# =============================================================================

EXTENSION_MAP: Dict[str, Optional[str]] = {
    ".py": "python",
    ".sql": "jinja_sql",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".csv": "csv",
    ".md": None,
    ".txt": None,
    ".toml": None,
    ".cfg": None,
    ".ini": None,
    ".in": None,
    ".lock": None,
}


class LanguageRouter:
    """Selects the correct tree-sitter grammar based on file extension."""

    def __init__(self) -> None:
        self._parsers: Dict[str, Any] = {}
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy-load tree-sitter grammars on first use."""
        if self._initialized:
            return
        try:
            from tree_sitter_languages import get_language, get_parser

            for lang in ("python", "sql", "yaml"):
                try:
                    parser = get_parser(lang)
                    self._parsers[lang] = parser
                except Exception as e:
                    logger.warning("Failed to load tree-sitter grammar for %s: %s", lang, e)
            self._initialized = True
        except ImportError:
            logger.error("tree-sitter-languages not installed. AST parsing unavailable.")
            self._initialized = True

    def get_parser(self, language: str) -> Optional[Any]:
        """Get tree-sitter parser for the given language."""
        self._ensure_initialized()
        return self._parsers.get(language)

    def classify(self, filepath: str) -> Optional[str]:
        """Classify file extension → language string."""
        ext = Path(filepath).suffix.lower()
        return EXTENSION_MAP.get(ext, None)


# =============================================================================
# Evidence Creation (MF-2)
# =============================================================================


def create_evidence(
    node: Any,
    file_path: str,
    source_text: str,
    method: str,
) -> Evidence:
    """Create Evidence from a tree-sitter node with verified snippet."""
    start_line, start_col = node.start_point
    end_line, end_col = node.end_point
    lines = source_text.splitlines()
    snippet_lines = lines[start_line : end_line + 1]
    snippet = "\n".join(snippet_lines) if snippet_lines else ""

    return Evidence(
        file_path=file_path,
        line_start=start_line + 1,  # 1-indexed for users
        line_end=end_line + 1,
        column_start=start_col,
        column_end=end_col,
        snippet=snippet,
        analysis_method=method,
    )


def create_evidence_from_line(
    file_path: str,
    line_num: int,
    source_text: str,
    method: str,
) -> Evidence:
    """Create Evidence from a specific line number."""
    lines = source_text.splitlines()
    snippet = lines[line_num - 1] if 0 < line_num <= len(lines) else ""
    return Evidence(
        file_path=file_path,
        line_start=line_num,
        line_end=line_num,
        column_start=0,
        column_end=len(snippet),
        snippet=snippet,
        analysis_method=method,
    )


# =============================================================================
# Tree-Sitter Analyzer
# =============================================================================


class TreeSitterAnalyzer:
    """Multi-language AST analyzer using tree-sitter with S-expression queries."""

    def __init__(self) -> None:
        self.router = LanguageRouter()
        self._file_cache: Dict[str, str] = {}

    def _read_file(self, filepath: str, repo_root: str) -> str:
        """Read file contents with caching."""
        full_path = str(Path(repo_root) / filepath)
        if full_path not in self._file_cache:
            try:
                self._file_cache[full_path] = Path(full_path).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                self._file_cache[full_path] = ""
        return self._file_cache[full_path]

    def analyze_module(self, filepath: str, repo_root: str) -> ModuleNode:
        """Analyze a single file and return a ModuleNode.

        Routes to language-specific analyzer. Graceful degradation on errors.
        """
        language = self.router.classify(filepath)

        if language is None:
            return ModuleNode(
                path=filepath,
                language="unknown",
                lines_of_code=0,
                is_complete_parse=True,
            )

        if language == "csv":
            return self._analyze_csv(filepath, repo_root)

        source = self._read_file(filepath, repo_root)
        if not source.strip():
            return ModuleNode(
                path=filepath,
                language=language,
                lines_of_code=0,
                is_complete_parse=True,
            )

        try:
            if language == "python":
                return self._analyze_python(filepath, source, repo_root)
            elif language in ("sql", "jinja_sql"):
                return self._analyze_sql(filepath, source, repo_root)
            elif language == "yaml":
                return self._analyze_yaml(filepath, source, repo_root)
            else:
                return ModuleNode(
                    path=filepath,
                    language=language,
                    lines_of_code=len(source.splitlines()),
                    is_complete_parse=True,
                )
        except Exception as e:
            logger.warning("Failed to analyze %s: %s", filepath, e)
            return ModuleNode(
                path=filepath,
                language=language if language else "unknown",
                lines_of_code=len(source.splitlines()) if source else 0,
                is_complete_parse=False,
                parse_errors=[
                    AnalysisError(
                        error_type="parse_error",
                        file_path=filepath,
                        message=str(e),
                        recoverable=True,
                        fallback_used="minimal_placeholder",
                    )
                ],
            )

    # -------------------------------------------------------------------------
    # CSV Analysis
    # -------------------------------------------------------------------------

    def _analyze_csv(self, filepath: str, repo_root: str) -> ModuleNode:
        """Minimal analysis for CSV seed files."""
        source = self._read_file(filepath, repo_root)
        return ModuleNode(
            path=filepath,
            language="csv",
            lines_of_code=len(source.splitlines()),
            is_complete_parse=True,
            is_entry_point=True,
            entry_point_type="seed",
        )

    # -------------------------------------------------------------------------
    # Python Analysis (M-2, M-3, M-6, F-1, C-1, C-2)
    # -------------------------------------------------------------------------

    def _analyze_python(self, filepath: str, source: str, repo_root: str) -> ModuleNode:
        """Full Python analysis: imports, functions, classes, complexity, comments."""
        parser = self.router.get_parser("python")
        parse_errors: List[AnalysisError] = []
        is_complete = True

        imports: List[str] = []
        public_functions: List[str] = []
        classes: List[str] = []
        unresolved: List[UnresolvedReference] = []
        is_entry_point = False

        if parser:
            try:
                tree = parser.parse(source.encode("utf-8"))
                root = tree.root_node

                if getattr(root, "has_error", False):
                    is_complete = False
                    parse_errors.append(
                        AnalysisError(
                            error_type="partial_parse",
                            file_path=filepath,
                            message="Tree-sitter encountered syntax errors",
                            recoverable=True,
                            fallback_used="partial_results",
                        )
                    )

                imports, unresolved = self._extract_python_imports(
                    root, source, filepath, repo_root
                )
                public_functions = self._extract_python_functions(root, source)
                classes = self._extract_python_classes(root, source)
                datasets_read, datasets_written = self._extract_python_data_flows(root, source)
                is_entry_point = self._detect_python_entry_point(root, source)
            except Exception as e:
                logger.warning("Tree-sitter Python parse error for %s: %s", filepath, e)
                is_complete = False
                parse_errors.append(
                    AnalysisError(
                        error_type="partial_parse",
                        file_path=filepath,
                        message=f"Tree-sitter parse error: {e}",
                        recoverable=True,
                        fallback_used="partial_results",
                    )
                )
        else:
            # Fallback: regex-based extraction
            imports = self._extract_python_imports_regex(source)
            public_functions = self._extract_python_functions_regex(source)
            datasets_read, datasets_written = [], []
            is_entry_point = '__name__' in source and '__main__' in source

        complexity = self._calculate_cyclomatic_complexity_python(source, parser)
        comment_ratio = self._calculate_comment_ratio(source, parser)

        return ModuleNode(
            path=filepath,
            language="python",
            complexity_score=complexity,
            imports=imports,
            public_functions=public_functions,
            classes=classes,
            datasets_read=datasets_read,
            datasets_written=datasets_written,
            lines_of_code=len(source.splitlines()),
            comment_ratio=comment_ratio,
            is_complete_parse=is_complete,
            parse_errors=parse_errors,
            is_entry_point=is_entry_point,
            entry_point_type="cli" if is_entry_point else None,
        )

    def _extract_python_imports(
        self, root: Any, source: str, filepath: str, repo_root: str
    ) -> Tuple[List[str], List[UnresolvedReference]]:
        """Extract Python imports using tree-sitter AST walk."""
        imports: List[str] = []
        unresolved: List[UnresolvedReference] = []

        for node in self._walk_tree(root):
            if node.type == "import_statement":
                # import foo.bar
                for child in node.children:
                    if child.type == "dotted_name":
                        imports.append(child.text.decode("utf-8"))
                    elif child.type == "aliased_import":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            imports.append(name_node.text.decode("utf-8"))

            elif node.type == "import_from_statement":
                module_node = node.child_by_field_name("module_name")
                if module_node:
                    module_text = module_node.text.decode("utf-8")
                    if module_text.startswith("."):
                        resolved = self._resolve_relative_import(
                            module_text, filepath, repo_root
                        )
                        imports.append(resolved)
                    else:
                        imports.append(module_text)

            elif node.type == "call":
                # Detect __import__() and importlib.import_module() (M-3)
                func_node = node.child_by_field_name("function")
                if func_node:
                    func_text = func_node.text.decode("utf-8")
                    if func_text == "__import__" or func_text.endswith("import_module"):
                        reason = "variable"
                        args_node = node.child_by_field_name("arguments")
                        if args_node and getattr(args_node, "named_children", []):
                            first_arg = args_node.named_children[0]
                            if first_arg.type == "string":
                                if first_arg.text.decode("utf-8").startswith(("f", "F")):
                                    reason = "fstring"
                                else:
                                    reason = "dynamic_string"
                            elif first_arg.type == "call":
                                reason = "function_return"
                            elif first_arg.type == "identifier":
                                reason = "variable"

                        unresolved.append(
                            UnresolvedReference(
                                ref_type="dynamic_import",
                                raw_text=node.text.decode("utf-8"),
                                source_file=filepath,
                                source_line=node.start_point[0] + 1,
                                reason=reason,
                            )
                        )

        return imports, unresolved

    def _extract_python_functions(self, root: Any, source: str) -> List[str]:
        """Extract public function names from Python AST."""
        functions: List[str] = []
        for node in self._walk_tree(root):
            if node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = name_node.text.decode("utf-8")
                    if not name.startswith("_"):
                        params_node = node.child_by_field_name("parameters")
                        params = params_node.text.decode("utf-8") if params_node else "()"
                        functions.append(f"{name}{params}")
        return functions

    def _extract_python_data_flows(self, root: Any, source: str) -> Tuple[List[str], List[str]]:
        """Extract Pandas/PySpark reads and writes by reconstructing method chains."""
        reads: List[str] = []
        writes: List[str] = []
        
        for node in self._walk_tree(root):
            if node.type == "call":
                chain = self._get_method_chain_name(node.child_by_field_name("function"))
                if not chain:
                    continue
                    
                full_chain = ".".join(chain)
                
                # Pandas simple reads/writes (e.g., pd.read_csv('...'), df.to_parquet('...'))
                if any(r in full_chain for r in ("read_csv", "read_json", "read_table", "read_gbq", "read_parquet")):
                    arg = self._get_first_string_arg(node)
                    if arg:
                        reads.append(arg)
                    else:
                        logger.info("Dynamic reference, cannot resolve: %s at line %d", full_chain, node.start_point[0] + 1)
                elif any(w in full_chain for w in ("to_csv", "to_json", "to_gbq", "to_parquet", "to_sql")):
                    arg = self._get_first_string_arg(node)
                    if arg:
                        writes.append(arg)
                    else:
                        logger.info("Dynamic reference, cannot resolve: %s at line %d", full_chain, node.start_point[0] + 1)
                
                # PySpark chains (e.g., spark.read.format('parquet').load('...'))
                # For PySpark, we typically care about the load()/save()/csv()/parquet() call
                elif "read" in chain and any(m in chain for m in ("load", "csv", "parquet", "json", "format")):
                    # the dataset path is usually the argument to load, csv, parquet, json
                    if chain[-1] in ("load", "csv", "parquet", "json"):
                        arg = self._get_first_string_arg(node)
                        if arg:
                            reads.append(arg)
                        else:
                            logger.info("Dynamic reference, cannot resolve: %s at line %d", full_chain, node.start_point[0] + 1)
                        
                elif "write" in chain and any(m in chain for m in ("save", "csv", "parquet", "json", "mode", "format", "saveAsTable")):
                    if chain[-1] in ("save", "csv", "parquet", "json", "saveAsTable"):
                        arg = self._get_first_string_arg(node)
                        if arg:
                            writes.append(arg)
                        else:
                            logger.info("Dynamic reference, cannot resolve: %s at line %d", full_chain, node.start_point[0] + 1)
                        
        return reads, writes

    def _get_method_chain_name(self, node: Any) -> List[str]:
        """Recursively build the method chain parts (e.g. spark, read, format, load)"""
        if not node:
            return []
        if node.type == "identifier":
            return [node.text.decode("utf-8")]
        if node.type == "attribute":
            obj = self._get_method_chain_name(node.child_by_field_name("object"))
            attr_node = node.child_by_field_name("attribute")
            attr = attr_node.text.decode("utf-8") if attr_node else ""
            return obj + [attr] if attr else obj
        if node.type == "call":
            return self._get_method_chain_name(node.child_by_field_name("function"))
        return []

    def _get_first_string_arg(self, node: Any) -> Optional[str]:
        """Extract the string value of the first string argument from a call."""
        args_node = node.child_by_field_name("arguments")
        if not args_node or not getattr(args_node, "named_children", []):
            return None
            
        for child in args_node.named_children:
            # handle regular positional args
            if child.type == "string":
                # strip quotes
                text = child.text.decode("utf-8")
                return text[1:-1] if len(text) >= 2 else text
            # handle keyword args like path='...'
            if child.type == "keyword_argument":
                val = child.child_by_field_name("value")
                if val and val.type == "string":
                    text = val.text.decode("utf-8")
                    return text[1:-1] if len(text) >= 2 else text
            # Continue scanning — don't bail on non-string positional args
        return None

    def _extract_python_classes(self, root: Any, source: str) -> List[str]:
        """Extract class names with inheritance from Python AST."""
        classes: List[str] = []
        for node in self._walk_tree(root):
            if node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = name_node.text.decode("utf-8")
                    bases_node = node.child_by_field_name("superclasses")
                    if bases_node:
                        bases = bases_node.text.decode("utf-8")
                        classes.append(f"{name}{bases}")
                    else:
                        classes.append(name)
        return classes

    def _detect_python_entry_point(self, root: Any, source: str) -> bool:
        """Detect if __name__ == '__main__' pattern (F-9)."""
        for node in self._walk_tree(root):
            if node.type == "if_statement":
                condition = node.child_by_field_name("condition")
                if condition:
                    text = condition.text.decode("utf-8")
                    if "__name__" in text and "__main__" in text:
                        return True
        return False

    def _calculate_cyclomatic_complexity_python(
        self, source: str, parser: Any
    ) -> int:
        """Cyclomatic complexity: M = decision_points + 1 (F-1, C-1).

        Decision nodes: if, elif, for, while, except, match, boolean operators,
        conditional expressions (ternary).
        """
        if not parser:
            # Regex fallback
            decision_keywords = r"\b(if|elif|for|while|except|match)\b"
            bool_ops = r"\b(and|or)\b"
            count = len(re.findall(decision_keywords, source))
            count += len(re.findall(bool_ops, source))
            return count + 1

        try:
            tree = parser.parse(source.encode("utf-8"))
            root = tree.root_node
            decision_types = {
                "if_statement", "elif_clause", "for_statement",
                "while_statement", "except_clause", "match_statement",
                "boolean_operator", "conditional_expression",
            }
            count = 0
            for node in self._walk_tree(root):
                if node.type in decision_types:
                    count += 1
            return count + 1
        except Exception:
            return 1

    def _calculate_comment_ratio(self, source: str, parser: Any) -> float:
        """Comment density: comment_lines / total_lines (C-2, line-based)."""
        total_lines = len(source.splitlines())
        if total_lines == 0:
            return 0.0

        if not parser:
            # Regex fallback: count lines starting with #
            comment_count = sum(
                1 for line in source.splitlines() if line.strip().startswith("#")
            )
            return comment_count / total_lines

        try:
            tree = parser.parse(source.encode("utf-8"))
            comment_lines: set[int] = set()
            for node in self._walk_tree(tree.root_node):
                if node.type == "comment":
                    for row in range(node.start_point[0], node.end_point[0] + 1):
                        comment_lines.add(row)
            return len(comment_lines) / total_lines
        except Exception:
            return 0.0

    def _resolve_relative_import(
        self, module_text: str, current_file: str, repo_root: str
    ) -> str:
        """Resolve relative imports via filesystem (M-6)."""
        dots = len(module_text) - len(module_text.lstrip("."))
        base_dir = Path(current_file).parent
        for _ in range(dots - 1):
            base_dir = base_dir.parent
        relative_module = module_text.lstrip(".")
        if relative_module:
            resolved = base_dir / relative_module.replace(".", "/")
        else:
            resolved = base_dir

        # Check if it's a file or package
        root = Path(repo_root)
        if (root / f"{resolved}.py").exists():
            return str(resolved)
        if (root / resolved / "__init__.py").exists():
            return str(resolved / "__init__")
        return f"UNRESOLVED:{module_text}"

    # Regex fallbacks for when tree-sitter isn't available
    def _extract_python_imports_regex(self, source: str) -> List[str]:
        """Regex fallback for Python import extraction."""
        imports = []
        for line in source.splitlines():
            line = line.strip()
            if line.startswith("import "):
                parts = line.replace("import ", "").split(",")
                for p in parts:
                    imports.append(p.strip().split(" as ")[0])
            elif line.startswith("from "):
                match = re.match(r"from\s+([\w.]+)\s+import", line)
                if match:
                    imports.append(match.group(1))
        return imports

    def _extract_python_functions_regex(self, source: str) -> List[str]:
        """Regex fallback for Python function extraction."""
        functions = []
        for line in source.splitlines():
            match = re.match(r"^def\s+(\w+)\s*\(", line)
            if match and not match.group(1).startswith("_"):
                functions.append(match.group(1))
        return functions

    # -------------------------------------------------------------------------
    # SQL / dbt Analysis (Jinja preprocessing + ref/source extraction)
    # -------------------------------------------------------------------------

    def _analyze_sql(self, filepath: str, source: str, repo_root: str) -> ModuleNode:
        """Analyze SQL/dbt file: extract refs, sources, CTEs."""
        imports: List[str] = []
        unresolved: List[UnresolvedReference] = []

        # Extract dbt ref() calls
        ref_pattern = re.compile(r"\{\{\s*ref\(\s*'(\w+)'\s*\)\s*\}\}")
        for match in ref_pattern.finditer(source):
            imports.append(match.group(1))

        # Extract dbt source() calls
        source_pattern = re.compile(
            r"\{\{\s*source\(\s*'(\w+)'\s*,\s*'(\w+)'\s*\)\s*\}\}"
        )
        for match in source_pattern.finditer(source):
            imports.append(f"source:{match.group(1)}.{match.group(2)}")

        # Detect dynamic / macro-wrapped refs → UnresolvedReference
        dynamic_ref_pattern = re.compile(
            r"\{\{\s*ref\(\s*(?!')[^)]+\)\s*\}\}"
        )
        for match in dynamic_ref_pattern.finditer(source):
            line_num = source[: match.start()].count("\n") + 1
            inner_text = re.search(r"ref\(\s*([^)]+)\s*\)", match.group(0))
            reason = "variable"
            if inner_text:
                inner = inner_text.group(1).strip()
                if inner.startswith("var("):
                    reason = "variable"
                elif inner.startswith("'") or inner.startswith('"'):
                    reason = "dynamic_string"
                elif "(" in inner:
                    reason = "function_return"
                else:
                    reason = "variable"

            unresolved.append(
                UnresolvedReference(
                    ref_type="macro_ref",
                    raw_text=match.group(0),
                    source_file=filepath,
                    source_line=line_num,
                    reason=reason,
                )
            )

        # Detect macro calls (e.g., {{ cents_to_dollars('price') }})
        macro_pattern = re.compile(r"\{\{\s*(\w+)\(")
        macro_calls = [
            m.group(1) for m in macro_pattern.finditer(source)
            if m.group(1) not in ("ref", "source", "config", "var", "env_var", "return")
        ]
        macro_calls = list(set(macro_calls))

        # Extract CTE names
        cte_pattern = re.compile(r"(\w+)\s+as\s*\(", re.IGNORECASE)
        ctes = [m.group(1) for m in cte_pattern.finditer(source)]

        # Try tree-sitter for SQL complexity
        parser = self.router.get_parser("sql")
        complexity = 1
        comment_ratio = 0.0
        if parser:
            try:
                # Preprocess Jinja before parsing SQL
                clean_sql = self._preprocess_jinja_for_treesitter(source)
                tree = parser.parse(clean_sql.encode("utf-8"))
                # Count CASE, WHEN, JOIN as decision points for SQL complexity
                decision_types = {"case", "when", "join_clause"}
                count = 0
                for node in self._walk_tree(tree.root_node):
                    if node.type.lower() in decision_types or "join" in node.type.lower():
                        count += 1
                complexity = count + 1

                # Comment ratio for SQL
                comment_lines: set[int] = set()
                for node in self._walk_tree(tree.root_node):
                    if node.type in ("comment", "line_comment", "block_comment"):
                        for row in range(node.start_point[0], node.end_point[0] + 1):
                            comment_lines.add(row)
                total = len(source.splitlines())
                comment_ratio = len(comment_lines) / total if total > 0 else 0.0
            except Exception:
                pass
        else:
            # Regex fallback for SQL comments
            total = len(source.splitlines())
            comment_count = sum(
                1 for line in source.splitlines()
                if line.strip().startswith("--") or line.strip().startswith("/*")
            )
            comment_ratio = comment_count / total if total > 0 else 0.0

        is_macro = "macros/" in filepath.replace("\\", "/")
        macro_name = Path(filepath).stem if is_macro else None
        
        return ModuleNode(
            path=filepath,
            language="jinja_sql",
            complexity_score=complexity,
            imports=imports,
            public_functions=[macro_name] if macro_name else [],
            called_macros=macro_calls,
            classes=[],
            cte_definitions=ctes,  # CTEs stored in their own structural field
            lines_of_code=len(source.splitlines()),
            comment_ratio=comment_ratio,
            is_complete_parse=True,
        )

    def _preprocess_jinja_for_treesitter(self, source: str) -> str:
        """Replace Jinja tags with SQL-safe placeholders for tree-sitter."""
        # Replace ref/source with table name placeholders
        clean = re.sub(
            r"\{\{\s*ref\(\s*'(\w+)'\s*\)\s*\}\}",
            r"__dbt_ref__\1",
            source,
        )
        clean = re.sub(
            r"\{\{\s*source\(\s*'(\w+)'\s*,\s*'(\w+)'\s*\)\s*\}\}",
            r"__dbt_source__\1__\2",
            clean,
        )
        # Replace other Jinja expressions with NULL
        clean = re.sub(r"\{\{.*?\}\}", "NULL", clean)
        # Remove Jinja blocks
        clean = re.sub(r"\{%.*?%\}", "", clean, flags=re.DOTALL)
        # Remove Jinja comments
        clean = re.sub(r"\{#.*?#\}", "", clean, flags=re.DOTALL)
        return clean

    # -------------------------------------------------------------------------
    # YAML Analysis (M-5)
    # -------------------------------------------------------------------------

    def _analyze_yaml(self, filepath: str, source: str, repo_root: str) -> ModuleNode:
        """Analyze YAML files (dbt config, sources, model definitions)."""
        imports: List[str] = []
        parse_errors: List[AnalysisError] = []
        is_complete = True

        try:
            data = yaml.safe_load(source)
            if not isinstance(data, dict):
                data = {}
        except yaml.YAMLError as e:
            logger.warning("YAML parse error in %s: %s", filepath, e)
            data = {}
            is_complete = False
            parse_errors.append(
                AnalysisError(
                    error_type="parse_error",
                    file_path=filepath,
                    message=f"YAML parse error: {e}",
                    recoverable=True,
                    fallback_used="minimal_placeholder",
                )
            )

        # Extract dbt source references from YAML
        if "sources" in data:
            for src in data.get("sources", []):
                if isinstance(src, dict):
                    for table in src.get("tables", []):
                        if isinstance(table, dict):
                            imports.append(
                                f"source:{src.get('name', '?')}.{table.get('name', '?')}"
                            )

        # Extract model references from models YAML
        if "models" in data:
            for model in data.get("models", []):
                if isinstance(model, dict):
                    imports.append(f"configures:{model.get('name', '?')}")

        # Determine if this configures other things
        filename = Path(filepath).name

        return ModuleNode(
            path=filepath,
            language="yaml",
            complexity_score=1,
            imports=imports,
            lines_of_code=len(source.splitlines()),
            comment_ratio=self._yaml_comment_ratio(source),
            is_complete_parse=is_complete,
            parse_errors=parse_errors,
        )

    def _yaml_comment_ratio(self, source: str) -> float:
        """Comment ratio for YAML (lines starting with #)."""
        lines = source.splitlines()
        if not lines:
            return 0.0
        comment_count = sum(1 for line in lines if line.strip().startswith("#"))
        return comment_count / len(lines)

    # -------------------------------------------------------------------------
    # Utility
    # -------------------------------------------------------------------------

    @staticmethod
    def _walk_tree(node: Any):
        """Depth-first walk of a tree-sitter node."""
        cursor = node.walk()
        visited = False

        while True:
            if not visited:
                yield cursor.node
                if cursor.goto_first_child():
                    continue

            if cursor.goto_next_sibling():
                visited = False
                continue

            if not cursor.goto_parent():
                break
            visited = True
