"""
Archivist Agent — Living Context Maintainer.

Produces and maintains the system's outputs as living artifacts:
- CODEBASE.md: Living context file for AI coding agent injection
- onboarding_brief.md: FDE Day-One Brief with evidence citations
- cartography_trace.jsonl: Audit log with confidence levels

This is the evolution of Week 1's CLAUDE.md and Week 2's Audit Report.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.agents.hydrologist import Hydrologist
from src.models.schemas import (
    CodebaseGraph,
    ContextWindowBudget,
    DayOneAnswer,
    ModuleNode,
)

logger = logging.getLogger(__name__)


class ArchivistAgent:
    """Generates and maintains living artifacts from the analysis pipeline.

    Consumes the fully populated CodebaseGraph (with PageRank, purpose
    statements, domain clusters from earlier phases) and the Hydrologist's
    lineage graph to produce structured, evidence-cited deliverables.
    """

    def __init__(self) -> None:
        self._trace_entries: List[Dict[str, Any]] = []

    # =========================================================================
    # Main Entry Point
    # =========================================================================

    def run(
        self,
        graph: CodebaseGraph,
        hydro: Hydrologist,
        day_one_answers: List[DayOneAnswer],
        semanticist_budget: Optional[ContextWindowBudget],
        output_dir: str,
    ) -> None:
        """Orchestrate all artifact generation in sequence."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        logger.info("Archivist: Generating CODEBASE.md ...")
        self.generate_codebase_md(graph, hydro, output_dir)
        self._log_trace("generate_codebase_md", "CODEBASE.md generated", 1.0, "static_analysis")

        logger.info("Archivist: Generating onboarding_brief.md ...")
        self.generate_onboarding_brief(graph, hydro, day_one_answers, output_dir)
        self._log_trace("generate_onboarding_brief", "Onboarding brief generated", 1.0, "static_analysis")

        logger.info("Archivist: Writing cartography_trace.jsonl ...")
        self.write_trace(output_dir, semanticist_budget)

        logger.info("Archivist: All artifacts generated successfully.")

    # =========================================================================
    # CODEBASE.md — Living Context for AI Agent Injection
    # =========================================================================

    def generate_codebase_md(
        self,
        graph: CodebaseGraph,
        hydro: Hydrologist,
        output_dir: str,
    ) -> str:
        """Generate CODEBASE.md structured for direct injection into AI agents.

        Sections:
        1. Architecture Overview (1 paragraph)
        2. Critical Path (top 5 by PageRank)
        3. Data Sources & Sinks (from Hydrologist)
        4. Known Debt (circular deps + doc drift)
        5. High-Velocity Files (change hotspots)
        6. Module Purpose Index (full table)
        """
        modules = graph.modules
        out = Path(output_dir)
        lines: List[str] = []

        # ── Section 1: Architecture Overview ────────────────────────────────
        lang_counts = Counter(m.language for m in modules)
        lang_summary = ", ".join(f"{count} {lang}" for lang, count in lang_counts.most_common())

        domain_counts = Counter(m.domain_cluster or "uncategorized" for m in modules)
        domain_summary = ", ".join(f"{name} ({count})" for name, count in domain_counts.most_common(5))

        total_loc = sum(m.lines_of_code for m in modules)
        entry_pts = [m for m in modules if m.is_entry_point]

        lines.append("# CODEBASE.md — Living Architectural Context\n")
        lines.append(f"**Generated:** {datetime.now().isoformat()}\n")
        lines.append(f"**Repository:** `{graph.repo_path}`\n\n")

        lines.append("## Architecture Overview\n\n")
        lines.append(
            f"This codebase contains **{len(modules)} modules** ({lang_summary}) "
            f"totaling **{total_loc:,} lines of code**. "
            f"It is organized into {len(domain_counts)} inferred domains: {domain_summary}. "
            f"There are **{len(entry_pts)} entry points** "
            f"and **{len(graph.transformations)} data transformations** tracked.\n\n"
        )

        # ── Section 2: Critical Path (Top 5 by PageRank) ───────────────────
        lines.append("## Critical Path\n\n")
        lines.append("The most architecturally significant modules (by PageRank):\n\n")
        lines.append("| Rank | Module | PageRank | Domain | Purpose |\n")
        lines.append("|:-----|:-------|:---------|:-------|:--------|\n")
        critical = sorted(modules, key=lambda m: m.pagerank, reverse=True)[:5]
        for i, m in enumerate(critical, 1):
            purpose = (m.purpose_statement or "—")[:100]
            domain = m.domain_cluster or "—"
            lines.append(f"| {i} | `{m.path}` | {m.pagerank:.4f} | {domain} | {purpose} |\n")
        lines.append("\n")

        # ── Section 3: Data Sources & Sinks ─────────────────────────────────
        sources = hydro.find_sources()
        sinks = hydro.find_sinks()

        lines.append("## Data Sources & Sinks\n\n")
        lines.append(f"**Sources (in-degree=0):** {len(sources)} data entry points\n\n")
        for s in sources[:15]:
            lines.append(f"- `{s}`\n")
        if len(sources) > 15:
            lines.append(f"- ... and {len(sources) - 15} more\n")

        lines.append(f"\n**Sinks (out-degree=0):** {len(sinks)} final outputs\n\n")
        for s in sinks[:15]:
            lines.append(f"- `{s}`\n")
        if len(sinks) > 15:
            lines.append(f"- ... and {len(sinks) - 15} more\n")
        lines.append("\n")

        # ── Section 4: Known Debt ───────────────────────────────────────────
        lines.append("## Known Debt\n\n")

        # Circular dependencies
        circ = graph.circular_dependencies
        if circ:
            lines.append(f"### Circular Dependencies ({len(circ)} detected)\n\n")
            for cd in circ[:5]:
                cycle = " → ".join(f"`{p}`" for p in cd.cycle_path)
                lines.append(f"- {cycle}\n")
                lines.append(f"  *Suggestion:* {cd.suggestion}\n")
        else:
            lines.append("### Circular Dependencies\n\nNone detected. ✅\n")
        lines.append("\n")

        # Documentation drift
        drift_modules = [m for m in modules if m.doc_drift]
        if drift_modules:
            lines.append(f"### Documentation Drift ({len(drift_modules)} files)\n\n")
            lines.append("Modules where the implementation contradicts the docstring:\n\n")
            for m in drift_modules[:10]:
                lines.append(f"- `{m.path}`\n")
            if len(drift_modules) > 10:
                lines.append(f"- ... and {len(drift_modules) - 10} more\n")
        else:
            lines.append("### Documentation Drift\n\nNo discrepancies detected. ✅\n")
        lines.append("\n")

        # Dead code
        dead = graph.dead_code_candidates
        if dead:
            lines.append(f"### Dead Code Candidates ({len(dead)} flagged)\n\n")
            for dc in sorted(dead, key=lambda x: x.confidence, reverse=True)[:5]:
                lines.append(f"- `{dc.module_path}` (confidence: {dc.confidence:.0%}) — {dc.explanation}\n")
        lines.append("\n")

        # ── Section 5: High-Velocity Files ──────────────────────────────────
        lines.append("## High-Velocity Files\n\n")
        lines.append("Files changing most frequently (likely pain points or active development):\n\n")
        high_vel = sorted(modules, key=lambda m: m.change_velocity_30d, reverse=True)[:10]
        has_velocity = any(m.change_velocity_30d > 0 for m in high_vel)
        if has_velocity:
            lines.append("| File | Velocity (30d) | Last Modified |\n")
            lines.append("|:-----|:--------------:|:--------------|\n")
            for m in high_vel:
                if m.change_velocity_30d > 0:
                    lines.append(f"| `{m.path}` | {m.change_velocity_30d:.2f} | {m.last_modified or 'N/A'} |\n")
        else:
            lines.append("No files changed in the last 30 days (archived/stable repository).\n")
            recent = sorted(
                [m for m in modules if m.last_modified],
                key=lambda m: m.last_modified or "",
                reverse=True,
            )[:5]
            if recent:
                lines.append("\n**Most recently modified:**\n\n")
                for m in recent:
                    lines.append(f"- `{m.path}` — {m.last_modified}\n")
        lines.append("\n")

        # ── Section 6: Module Purpose Index ─────────────────────────────────
        lines.append("## Module Purpose Index\n\n")
        lines.append("| Module | Language | Domain | Purpose |\n")
        lines.append("|:-------|:---------|:-------|:--------|\n")
        for m in sorted(modules, key=lambda x: x.path):
            purpose = (m.purpose_statement or "—")[:120]
            domain = m.domain_cluster or "—"
            lines.append(f"| `{m.path}` | {m.language} | {domain} | {purpose} |\n")
        lines.append("\n")

        content = "".join(lines)
        codebase_path = out / "CODEBASE.md"
        codebase_path.write_text(content, encoding="utf-8")
        logger.info(f"Saved CODEBASE.md to {codebase_path} ({len(content)} bytes)")
        return content

    # =========================================================================
    # onboarding_brief.md — FDE Day-One Brief
    # =========================================================================

    def generate_onboarding_brief(
        self,
        graph: CodebaseGraph,
        hydro: Hydrologist,
        day_one_answers: List[DayOneAnswer],
        output_dir: str,
    ) -> str:
        """Generate the Day-One Brief answering the 5 FDE questions.

        Uses LLM-generated answers when available (from Semanticist), falls
        back to static analysis when LLM answers are empty.
        """
        modules = graph.modules
        out = Path(output_dir)
        lines: List[str] = []

        lines.append("# FDE Day-One Brief\n\n")
        lines.append(f"Generated by The Brownfield Cartographer — {datetime.now().isoformat()}\n\n")
        lines.append(f"**Repository:** `{graph.repo_path}`\n\n")
        lines.append("---\n\n")

        if day_one_answers:
            # LLM-generated answers with evidence
            for ans in day_one_answers:
                lines.append(f"## {ans.question}\n\n")
                lines.append(f"{ans.answer}\n\n")
                if ans.evidence:
                    lines.append("**Evidence:**\n\n")
                    for ev in ans.evidence:
                        lines.append(f"- `{ev.file}:{ev.line}` *(llm_inference)*\n")
                else:
                    lines.append("**Evidence:** No specific citations.\n")
                lines.append("\n---\n\n")
        else:
            # Static fallback — same quality, generated from graph data
            logger.info("Using static fallback for Day-One Brief (LLM unavailable).")
            lines.extend(self._static_q1_ingestion(modules, hydro))
            lines.extend(self._static_q2_critical_outputs(modules))
            lines.extend(self._static_q3_blast_radius(modules, hydro))
            lines.extend(self._static_q4_business_logic(modules))
            lines.extend(self._static_q5_git_velocity(modules))

        content = "".join(lines)
        brief_path = out / "onboarding_brief.md"
        brief_path.write_text(content, encoding="utf-8")
        logger.info(f"Saved onboarding_brief.md to {brief_path}")
        return content

    # ── Static Fallback Question Generators ─────────────────────────────────

    def _static_q1_ingestion(self, modules: List[ModuleNode], hydro: Hydrologist) -> List[str]:
        lines: List[str] = []
        lines.append("## 1. What is the primary data ingestion path?\n\n")
        sources = hydro.find_sources()
        source_nodes = [s for s in sources if "source:" in s.lower() or "seed" in s.lower() or s.startswith("dataset:")]
        staging_mods = [m for m in modules if "staging" in m.path.lower() or "stg_" in m.path.lower()]

        if source_nodes:
            lines.append(f"**Sources identified ({len(source_nodes)}):**\n\n")
            for s in source_nodes[:10]:
                lines.append(f"- `{s}` *(static_analysis)*\n")
        if staging_mods:
            lines.append(f"\n**Staging models ({len(staging_mods)}):**\n\n")
            for m in staging_mods[:5]:
                lines.append(f"- `{m.path}` *(static_analysis)*\n")
        lines.append("\n---\n\n")
        return lines

    def _static_q2_critical_outputs(self, modules: List[ModuleNode]) -> List[str]:
        lines: List[str] = []
        lines.append("## 2. What are the 3-5 most critical output datasets?\n\n")
        critical = sorted(modules, key=lambda m: m.pagerank, reverse=True)[:5]
        for i, m in enumerate(critical, 1):
            purpose = f" — {m.purpose_statement}" if m.purpose_statement else ""
            lines.append(f"{i}. **`{m.path}`** — PageRank: {m.pagerank:.4f}{purpose} *(static_analysis)*\n")
        lines.append("\n---\n\n")
        return lines

    def _static_q3_blast_radius(self, modules: List[ModuleNode], hydro: Hydrologist) -> List[str]:
        lines: List[str] = []
        lines.append("## 3. What is the blast radius if the most critical module fails?\n\n")
        critical = sorted(modules, key=lambda m: m.pagerank, reverse=True)[:1]
        if critical:
            top_mod = critical[0]
            top_stem = Path(top_mod.path).stem
            blast_node = None
            for candidate in [f"transformation:{top_stem}", f"dataset:{top_stem}"]:
                if candidate in hydro.graph:
                    blast_node = candidate
                    break
            if blast_node:
                radius = hydro.blast_radius(blast_node)
                lines.append(f"**Module:** `{top_mod.path}` (node: `{blast_node}`)\n\n")
                lines.append(f"**Downstream impact:** {len(radius)} nodes affected *(graph_traversal)*\n\n")
                if radius:
                    for node, dist in sorted(radius.items(), key=lambda x: x[1])[:15]:
                        lines.append(f"- `{node}` (distance: {dist})\n")
            else:
                lines.append(f"**Module:** `{top_mod.path}` (no matching lineage node)\n")
        lines.append("\n---\n\n")
        return lines

    def _static_q4_business_logic(self, modules: List[ModuleNode]) -> List[str]:
        lines: List[str] = []
        lines.append("## 4. Where is the business logic concentrated vs. distributed?\n\n")
        by_dir: Dict[str, List[ModuleNode]] = defaultdict(list)
        for m in modules:
            d = str(Path(m.path).parent)
            by_dir[d].append(m)
        top_dirs = sorted(by_dir.items(), key=lambda kv: sum(m.complexity_score for m in kv[1]), reverse=True)[:5]
        for d, mods in top_dirs:
            total_cx = sum(m.complexity_score for m in mods)
            lines.append(f"- **`{d}/`** — {len(mods)} files, total complexity: {total_cx} *(static_analysis)*\n")
        entry_pts = [m for m in modules if m.is_entry_point]
        lines.append(f"\n**Entry points:** {len(entry_pts)} detected\n\n")
        for ep in entry_pts[:10]:
            lines.append(f"- `{ep.path}` (type: {ep.entry_point_type})\n")
        lines.append("\n---\n\n")
        return lines

    def _static_q5_git_velocity(self, modules: List[ModuleNode]) -> List[str]:
        lines: List[str] = []
        lines.append("## 5. What has changed most frequently in the last 30 days?\n\n")
        high_vel = sorted(modules, key=lambda m: m.change_velocity_30d, reverse=True)[:10]
        if any(m.change_velocity_30d > 0 for m in high_vel):
            lines.append("| File | Velocity (30d) | Last Modified |\n")
            lines.append("|:-----|:--------------:|:--------------|\n")
            for m in high_vel:
                if m.change_velocity_30d > 0:
                    lines.append(f"| `{m.path}` | {m.change_velocity_30d:.2f} | {m.last_modified or 'N/A'} |\n")
        else:
            lines.append("No files changed in the last 30 days (archived/stable repository).\n\n")
            recent = sorted([m for m in modules if m.last_modified], key=lambda m: m.last_modified or "", reverse=True)[:5]
            if recent:
                lines.append("**Most recently modified:**\n\n")
                for m in recent:
                    lines.append(f"- `{m.path}` — {m.last_modified}\n")
        lines.append("\n")
        return lines

    # =========================================================================
    # cartography_trace.jsonl — Audit Trail
    # =========================================================================

    def add_trace_entries(self, entries: List[Dict[str, Any]]) -> None:
        """Accept trace entries from the orchestrator pipeline."""
        self._trace_entries.extend(entries)

    def _log_trace(
        self,
        action: str,
        detail: str,
        confidence: float,
        evidence_source: str,
    ) -> None:
        """Append a trace entry internally."""
        self._trace_entries.append({
            "action": action,
            "detail": detail,
            "confidence": confidence,
            "evidence_source": evidence_source,
            "timestamp": datetime.now().isoformat(),
        })

    def write_trace(
        self,
        output_dir: str,
        budget: Optional[ContextWindowBudget] = None,
    ) -> None:
        """Write cartography_trace.jsonl with confidence and evidence_source fields."""
        out = Path(output_dir)
        trace_path = out / "cartography_trace.jsonl"

        # Append budget summary if available
        if budget:
            self._trace_entries.append({
                "action": "token_budget_summary",
                "bulk_input_tokens": budget.bulk_input_tokens,
                "bulk_output_tokens": budget.bulk_output_tokens,
                "synthesis_input_tokens": budget.synthesis_input_tokens,
                "synthesis_output_tokens": budget.synthesis_output_tokens,
                "estimated_cost_usd": budget.estimated_cost_usd,
                "confidence": 1.0,
                "evidence_source": "instrumentation",
                "timestamp": datetime.now().isoformat(),
            })

        with open(trace_path, "w", encoding="utf-8") as f:
            for entry in self._trace_entries:
                f.write(json.dumps(entry) + "\n")

        logger.info(f"Saved {len(self._trace_entries)} trace entries to {trace_path}")
