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
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Outfit:wght@300;400;500;600;700;800&display=swap');

    /* Global Variables & Base Typography */
    :root {
        --bg-color: #0d1117;
        --surface-color: rgba(22, 27, 34, 0.6);
        --surface-border: rgba(255, 255, 255, 0.08);
        --accent-glow: rgba(56, 189, 248, 0.15);
        --text-primary: #f0f6fc;
        --text-secondary: #8b949e;
        --gradient-primary: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
        --gradient-surface: linear-gradient(180deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.8) 100%);
    }

    html, body, [data-testid="stAppViewBlockContainer"], .stApp {
        background-color: #0d1117 !important;
        color: #f0f6fc !important;
    }

    [data-testid="stSidebar"], [data-testid="stSidebar"] > div {
        background-color: #161b22 !important;
    }

    /* Force all text elements to be light */
    p, span, div, label, .stMarkdown, [data-testid="stText"] {
        color: #f0f6fc !important;
    }

    /* Target specific Streamlit elements that often stay white */
    .element-container, .stAlert, .stChatMessage, .stExpander, .stTabs {
        background-color: transparent !important;
    }

    /* High-priority override for the main container */
    .main .block-container {
        background-color: #0d1117 !important;
        color: #f0f6fc !important;
    }


    /* Main Header Container */
    .main-header {
        position: relative;
        background: var(--gradient-surface);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        padding: 2.5rem 3rem;
        border-radius: 20px;
        margin-bottom: 2rem;
        border: 1px solid var(--surface-border);
        box-shadow: 
            0 4px 24px -1px rgba(0, 0, 0, 0.5),
            inset 0 1px 0 rgba(255, 255, 255, 0.1);
        overflow: hidden;
    }
    
    /* Header Glow Effect */
    .main-header::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0; height: 1px;
        background: linear-gradient(90deg, transparent, rgba(56, 189, 248, 0.5), transparent);
    }

    .main-header h1 {
        margin: 0;
        font-size: 2.5rem;
        font-weight: 800;
        background: linear-gradient(to right, #fff, #9ca3af);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -0.03em;
    }
    
    .main-header p {
        margin: 0.5rem 0 0 0;
        color: var(--text-secondary);
        font-size: 1.1rem;
        font-weight: 400;
    }

    /* Metric Cards (Glassmorphism) */
    .metric-card {
        background: var(--gradient-surface);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        padding: 1.5rem;
        border-radius: 16px;
        text-align: center;
        border: 1px solid var(--surface-border);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        height: 100%;
    }
    
    .metric-card:hover {
        transform: translateY(-4px);
        box-shadow: 0 12px 28px rgba(0, 0, 0, 0.4), 0 0 16px var(--accent-glow);
        border-color: rgba(255, 255, 255, 0.15);
    }
    
    .metric-card h3 { 
        margin: 0; 
        font-size: 2.5rem; 
        font-weight: 700;
        color: #fff;
        line-height: 1.1;
    }
    
    .metric-card p { 
        margin: 0.5rem 0 0 0; 
        font-size: 0.9rem; 
        font-weight: 500;
        color: var(--text-secondary);
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    /* Tabs Styling - Pill Design */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0.5rem;
        background-color: transparent;
        padding-bottom: 0.5rem;
    }
    
    .stTabs [data-baseweb="tab"] {
        border-radius: 99px;
        padding: 0.5rem 1.25rem;
        font-family: 'Outfit', sans-serif;
        font-weight: 500;
        font-size: 0.95rem;
        background-color: transparent;
        border: 1px solid transparent;
        color: var(--text-secondary);
        transition: all 0.2s ease;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        background-color: rgba(255, 255, 255, 0.05);
        color: #fff;
    }
    
    .stTabs [aria-selected="true"] {
        background: var(--surface-color) !important;
        border: 1px solid var(--surface-border) !important;
        color: #fff !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
    }
    
    /* Remove default tab border */
    .stTabs [data-baseweb="tab-border"] {
        display: none;
    }
    
    /* Input Fields & Select Boxes */
    div[data-baseweb="input"] > div, 
    div[data-baseweb="select"] > div,
    div[data-baseweb="base-input"] {
        background-color: rgba(13, 17, 23, 0.7) !important;
        border-radius: 8px;
        border: 1px solid var(--surface-border) !important;
        color: #fff !important;
        transition: all 0.2s ease;
    }
    
    div[data-baseweb="input"] > div:hover, 
    div[data-baseweb="select"] > div:hover {
        border-color: rgba(255, 255, 255, 0.2) !important;
    }

    /* Buttons */
    /* Buttons - Clean White Design */
    .stButton > button {
        background-color: #ffffff !important;
        color: #000000 !important;
        border: 1px solid rgba(0, 0, 0, 0.2) !important;
        border-radius: 6px !important;
        padding: 0.5rem 1rem !important;
        font-family: 'Inter', sans-serif !important;
        font-weight: 800 !important;
        font-size: 0.85rem !important;
        text-transform: none !important;
        letter-spacing: normal !important;
        transition: all 0.2s ease !important;
        box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1) !important;
    }
    
    .stButton > button:hover {
        background-color: #f3f4f6 !important;
        border-color: rgba(0, 0, 0, 0.2) !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.15) !important;
    }
    
    .stButton > button:active {
        transform: translateY(0);
        background-color: #e5e7eb !important;
    }
    
    /* Sidebar Restyling */
    [data-testid="stSidebar"] {
        background-color: rgba(13, 17, 23, 0.8) !important;
        border-right: 1px solid var(--surface-border);
    }
    
    [data-testid="stSidebar"] hr {
        border-color: var(--surface-border);
        margin: 1.5rem 0;
    }

    /* ----------- Navigator Chat Interface ----------- */
    
    /* Chat Message Bubbles */
    [data-testid="stChatMessage"] {
        background-color: var(--surface-color) !important;
        border: 1px solid var(--surface-border) !important;
        border-radius: 12px !important;
        padding: 1.5rem !important;
        margin-bottom: 1rem !important;
        width: 100% !important;
        max-width: 100% !important;
        display: block !important; /* Reverting flex to prevent internal squishing */
    }
    
    /* Ensure Avatars have space in block layout */
    [data-testid="stChatMessageAvatar"] {
        float: left !important;
        margin-right: 1.5rem !important;
        margin-bottom: 0.5rem !important;
    }
    
    /* Clear float and handle text wrapping */
    [data-testid="stChatMessageContent"] {
        display: block !important;
        overflow-wrap: break-word !important;
        word-wrap: break-word !important;
        word-break: break-word !important;
        width: auto !important;
    }
    
    [data-testid="stChatMessageContent"]::after {
        content: "";
        clear: both;
        display: table;
    }
    
    /* Chat Message Text inside bubbles */
    [data-testid="stChatMessage"] * {
        color: #ffffff !important;
    }
    
    /* User Message distinct style */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        background-color: rgba(59, 130, 246, 0.15) !important;
        border-color: rgba(59, 130, 246, 0.3) !important;
    }
    
    /* ----------- Chat Input Box ----------- */
    
    /* The outer container */
    [data-testid="stChatInput"] {
        background-color: transparent !important;
        border: none !important;
        padding-bottom: 2rem !important; /* Breathing room at bottom */
    }
    
    /* Force full width on the generic streamlit wrapper */
    .stChatInput {
        width: 100% !important;
        max-width: 100% !important;
    }
    
    /* The inner input area container */
    [data-testid="stChatInput"] > div,
    .stChatInputContainer {
        background-color: #1e293b !important; /* Dark slate background */
        border: 1px solid rgba(255, 255, 255, 0.2) !important;
        border-radius: 12px !important;
        padding: 0.75rem 1rem !important;
        box-sizing: border-box !important;
        display: flex !important;
        align-items: center !important;
        width: 100% !important;
        max-width: 100% !important; /* FORCE full width */
    }
    
    /* The actual text area where user types */
    [data-testid="stChatInputTextArea"] {
        color: #ffffff !important;
        background-color: transparent !important;
        caret-color: #ffffff !important;
        padding: 0 !important;
        min-height: 24px !important;
        flex-grow: 1 !important;
        width: 100% !important;
        border: none !important;
        outline: none !important;
    }
    
    /* Fallback for generic textareas inside the chat input block */
    [data-testid="stChatInput"] textarea {
        color: #ffffff !important;
        background-color: transparent !important;
        -webkit-text-fill-color: #ffffff !important;
        padding: 0 !important;
        margin: 0 !important;
        flex-grow: 1 !important;
        width: 100% !important;
        border: none !important;
        box-shadow: none !important;
    }
    
    /* Placeholder text */
    [data-testid="stChatInput"] textarea::placeholder {
        color: rgba(255, 255, 255, 0.6) !important;
        -webkit-text-fill-color: rgba(255, 255, 255, 0.6) !important;
    }
    
    /* Send Button inside chat input */
    [data-testid="stChatInputSubmitButton"] {
        color: #ffffff !important;
    }
    [data-testid="stChatInputSubmitButton"] svg {
        fill: #38bdf8 !important; /* Make send arrow prominent */
    }
    
    /* Number Input Stepper Buttons */
    button[kind="stepUp"], button[kind="stepDown"] {
        background-color: rgba(255,255,255,0.1) !important;
        color: white !important;
    }
    button[kind="stepUp"]:hover, button[kind="stepDown"]:hover {
        background-color: rgba(255,255,255,0.2) !important;
    }

    /* Inline Code Blocks in Markdown */
    .stMarkdown code {
        background-color: rgba(255, 255, 255, 0.1) !important;
        color: #e5e7eb !important;
        padding: 0.2rem 0.4rem !important;
        border-radius: 4px !important;
        border: 1px solid rgba(255,255,255,0.1) !important;
    }

    /* Fix specific white boxes rendered by Streamlit */
    .element-container, .stMarkdown {
        background-color: transparent !important;
    }
    
    /* Expander Arrow */
    summary svg {
        fill: white !important;
        color: white !important;
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
