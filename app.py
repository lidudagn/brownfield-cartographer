"""
Brownfield Cartographer — Streamlit Web UI

Optional interactive frontend for the Cartographer.
Launch via:  uv run src/cli.py ui
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# ── Page Config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Brownfield Cartographer",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    html, body, [class*="st-"] {
        font-family: 'Inter', sans-serif;
    }

    .main-header {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 1.5rem;
        color: white;
        box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    }
    .main-header h1 {
        margin: 0;
        font-size: 2rem;
        font-weight: 700;
        letter-spacing: -0.5px;
    }
    .main-header p {
        margin: 0.5rem 0 0 0;
        opacity: 0.8;
        font-size: 1rem;
    }

    .metric-card {
        background: linear-gradient(135deg, #1e293b, #334155);
        padding: 1.2rem;
        border-radius: 12px;
        text-align: center;
        color: white;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .metric-card h3 { margin: 0; font-size: 1.8rem; font-weight: 700; }
    .metric-card p  { margin: 0.3rem 0 0 0; font-size: 0.85rem; opacity: 0.7; }

    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px 8px 0 0;
        padding: 10px 20px;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)


# ── Helpers ─────────────────────────────────────────────────────────────────

GITHUB_URL_RE = re.compile(
    r"^(https?://|git@)(github\.com|gitlab\.com|bitbucket\.org)[/:][\w.\-]+/[\w.\-]+(?:/\w+)*(\.git)?/?$"
)


def _is_git_url(path: str) -> bool:
    return bool(GITHUB_URL_RE.match(path.strip()))


def _run_analysis(repo_path: str, output_dir: str, dialect: str, workers: int) -> bool:
    """Run the orchestrator pipeline. Returns True on success."""
    try:
        from src.orchestrator import run_analysis as _analyze
        result = _analyze(
            repo_path=repo_path,
            output_dir=output_dir,
            dialect=dialect,
            workers=workers,
        )
        return result is not None
    except Exception as e:
        st.error(f"Analysis failed: {e}")
        return False


def _load_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


# ── Sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🗺️ Cartographer")
    st.markdown("---")

    repo_input = st.text_input(
        "Repository Path or GitHub URL",
        placeholder="e.g. ../jaffle-shop or https://github.com/org/repo",
        help="Enter a local filesystem path or a GitHub/GitLab URL to analyze.",
    )

    col1, col2 = st.columns(2)
    with col1:
        dialect = st.selectbox("SQL Dialect", ["auto", "postgres", "bigquery", "snowflake", "duckdb"])
    with col2:
        workers = st.number_input("Workers", min_value=1, max_value=16, value=4)

    output_dir = st.text_input("Output Directory", value=".cartography", help="Where to save generated artifacts.")

    run_btn = st.button("🚀 Generate Cartography", use_container_width=True, type="primary")

    st.markdown("---")
    st.caption("CLI is still fully available:  \n`uv run src/cli.py analyze ...`")


# ── Header ──────────────────────────────────────────────────────────────────

st.markdown("""
<div class="main-header">
    <h1>🗺️ The Brownfield Cartographer</h1>
    <p>Codebase Intelligence System for Rapid FDE Onboarding</p>
</div>
""", unsafe_allow_html=True)


# ── Run Analysis ────────────────────────────────────────────────────────────

if run_btn:
    if not repo_input or not repo_input.strip():
        st.error("Please enter a repository path or GitHub URL.")
        st.stop()

    resolved_path = repo_input.strip()
    tmp_clone_dir = None

    # Handle GitHub URLs
    if _is_git_url(resolved_path):
        with st.spinner("Cloning repository..."):
            tmp_clone_dir = tempfile.mkdtemp(prefix="cartographer_clone_")
            repo_name = resolved_path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
            clone_path = os.path.join(tmp_clone_dir, repo_name)
            try:
                subprocess.run(
                    ["git", "clone", "--depth", "1", resolved_path, clone_path],
                    check=True, capture_output=True, text=True,
                )
                resolved_path = clone_path
            except subprocess.CalledProcessError as e:
                st.error(f"Failed to clone: {e.stderr}")
                shutil.rmtree(tmp_clone_dir, ignore_errors=True)
                st.stop()
    else:
        resolved_path = str(Path(resolved_path).absolute())

    abs_output = str(Path(output_dir).absolute())

    with st.spinner("🔬 Analyzing codebase... This may take a minute."):
        success = _run_analysis(resolved_path, abs_output, dialect, workers)

    if tmp_clone_dir:
        shutil.rmtree(tmp_clone_dir, ignore_errors=True)

    if success:
        st.success("✅ Analysis complete! Explore the results below.")
        st.balloons()
    else:
        st.warning("Analysis finished with warnings. Check logs for details.")


# ── Display Artifacts ───────────────────────────────────────────────────────

out = Path(output_dir).absolute()

if not (out / "module_graph.json").exists():
    st.info("👆 Enter a repository above and click **Generate Cartography** to begin.")
    st.stop()

# ── Metrics Row ─────────────────────────────────────────────────────────────
report = _load_json(out / "analysis_report.json")
if report and "summary" in report:
    s = report["summary"]
    cols = st.columns(4)
    metrics = [
        (s.get("modules_analyzed", 0), "Modules Analyzed"),
        (s.get("datasets_discovered", 0), "Datasets Found"),
        (s.get("transformations", 0), "Transformations"),
        (len(report.get("risk_analysis", {}).get("circular_dependencies", [])), "Circular Deps"),
    ]
    for col, (val, label) in zip(cols, metrics):
        col.markdown(f"""
        <div class="metric-card">
            <h3>{val}</h3>
            <p>{label}</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

# ── Tabs ────────────────────────────────────────────────────────────────────

tab_brief, tab_module, tab_lineage, tab_artifacts, tab_navigator = st.tabs([
    "📋 Day-One Brief",
    "🕸️ Module Graph",
    "🌊 Lineage Graph",
    "📂 Artifacts Explorer",
    "🧭 Navigator",
])

# Tab 1: Day-One Brief
with tab_brief:
    brief_path = out / "onboarding_brief.md"
    codebase_path = out / "CODEBASE.md"

    brief_md = _load_text(brief_path)
    if brief_md:
        st.markdown(brief_md)
    else:
        st.warning("onboarding_brief.md not found.")

    with st.expander("📄 View CODEBASE.md (AI Context File)"):
        codebase_md = _load_text(codebase_path)
        if codebase_md:
            st.markdown(codebase_md)
        else:
            st.info("CODEBASE.md not generated yet.")

# Tab 2: Module Graph
with tab_module:
    html_path = out / "module_graph.html"
    png_path = out / "module_graph.png"

    if html_path.exists():
        st.markdown("### Interactive Module Dependency Graph")
        st.caption("Drag nodes to explore. Hover for PageRank & Velocity metrics.")
        html_content = html_path.read_text(encoding="utf-8")
        components.html(html_content, height=800, scrolling=True)
    elif png_path.exists():
        st.markdown("### Module Dependency Graph (Static)")
        st.image(str(png_path))
    else:
        st.warning("No module graph visualization found.")

# Tab 3: Lineage Graph
with tab_lineage:
    lineage_html = out / "lineage_graph.html"

    if lineage_html.exists():
        st.markdown("### Interactive Data Lineage DAG")
        st.caption("🟢 Sources → 🔵 Staging → 🟠 Marts. Hover for details.")
        html_content = lineage_html.read_text(encoding="utf-8")
        components.html(html_content, height=800, scrolling=True)
    else:
        st.warning("No lineage graph HTML found. Run analysis first.")

# Tab 4: Artifacts Explorer
with tab_artifacts:
    st.markdown("### Browse Raw Artifacts")

    artifact_files = [
        "analysis_report.json",
        "datasets.json",
        "transformations.json",
        "modules.json",
        "edges.json",
        "lineage_graph.json",
        "cartography_trace.jsonl",
    ]

    available = [f for f in artifact_files if (out / f).exists()]

    if available:
        selected = st.selectbox("Select artifact to view:", available)
        file_path = out / selected

        if selected.endswith(".jsonl"):
            lines = file_path.read_text(encoding="utf-8").strip().split("\n")
            data = [json.loads(line) for line in lines if line.strip()]
            st.json(data)
        else:
            data = _load_json(file_path)
            if data:
                st.json(data)
            else:
                st.error(f"Failed to load {selected}")
    else:
        st.info("No artifact JSON files found.")

# Tab 5: Navigator
with tab_navigator:
    st.markdown("### 🧭 Ask the Navigator")
    st.caption("Query the codebase knowledge graph using natural language.")

    # Initialize chat history
    if "nav_messages" not in st.session_state:
        st.session_state.nav_messages = []

    # Display chat history
    for msg in st.session_state.nav_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("e.g. What is the blast radius of stg_orders?"):
        st.session_state.nav_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    from src.graph.knowledge_graph import KnowledgeGraphWrapped
                    from src.agents.hydrologist import Hydrologist
                    from src.agents.navigator import NavigatorAgent

                    graph_path = out / "module_graph.json"
                    wrapper = KnowledgeGraphWrapped.load(graph_path)
                    cg = wrapper.codebase

                    hydro = Hydrologist()
                    hydro.build_lineage_graph(cg)

                    nav = NavigatorAgent(cg, hydro, cg.repo_path)
                    response = nav.route_query(prompt)

                    st.markdown(response)
                    st.session_state.nav_messages.append({"role": "assistant", "content": response})
                except Exception as e:
                    error_msg = f"Navigator error: {e}"
                    st.error(error_msg)
                    st.session_state.nav_messages.append({"role": "assistant", "content": error_msg})
