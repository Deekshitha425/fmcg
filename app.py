import streamlit as st
import sqlite3, json, re, os, tempfile, pandas as pd
import google.generativeai as genai

# ── Page config ─────────────────────────────────────────────────────────
st.set_page_config(page_title="FMCG AI Assistant", page_icon="🥤", layout="centered")

st.markdown("""
<style>
.block-container{padding-top:1.5rem}
.main-title{font-size:2rem;font-weight:700;color:#fff;margin-bottom:0}
.sub-title{font-size:0.95rem;color:#888;margin-top:0;margin-bottom:1.2rem}
.answer-box{background:#1e2130;border-left:4px solid #4f8ef7;border-radius:8px;
            padding:1rem 1.2rem;color:#e8e8e8;font-size:0.97rem;line-height:1.6;margin-top:0.4rem}
.user-msg{background:#2a2d3e;border-radius:12px;padding:10px 14px;color:#fff;
          margin:6px 0;font-size:0.95rem}
.sql-box{background:#12141c;border-radius:6px;padding:0.8rem 1rem;
         font-family:monospace;font-size:0.8rem;color:#a8c7fa;white-space:pre-wrap}
</style>
""", unsafe_allow_html=True)

# ── Header ──────────────────────────────────────────────────────────────
st.markdown('<p class="main-title">🥤 FMCG AI Assistant</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-title">Ask any business question about beverages sales, inventory & promotions.</p>', unsafe_allow_html=True)

# ── Sidebar ─────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Settings")
    api_key = st.text_input(
        "Google Gemini API Key", type="password",
        value=st.secrets.get("GEMINI_API_KEY", ""),
        help="Free key from aistudio.google.com"
    )
    st.markdown("---")
    st.markdown("**📌 Sample Questions**")
    for q in [
        "Which region had the highest revenue?",
        "Top 5 products by units sold?",
        "Promo vs non-promo sales lift?",
        "Which store had the most stockouts?",
        "Revenue breakdown by category?",
        "Best performing brand in West?",
    ]:
        st.markdown(f"• {q}")

# ── Load DB (cached — runs once) ─────────────────────────────────────────
@st.cache_resource
def get_db():
    csv_path = os.path.join(os.path.dirname(__file__), "merged_data.csv")
    df = pd.read_csv(csv_path)
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(tmp.name, check_same_thread=False)
    df.to_sql("fmcg_data", conn, if_exists="replace", index=False)
    for col in ["product_id", "store_id", "week_start_date", "region", "promotion_flag"]:
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{col} ON fmcg_data({col})")
    conn.commit()
    return conn

# ── Schema for Gemini ────────────────────────────────────────────────────
SCHEMA = """
You are a SQL expert for an FMCG beverages analytics database (SQLite).
There is ONE table called fmcg_data with these columns:

  week_start_date TEXT    -- ISO date e.g. '2024-01-01'
  product_id      TEXT    -- e.g. 'BEV001'
  product_name    TEXT
  brand           TEXT
  category        TEXT    -- Juice, Water, Carbonated, Energy, Dairy
  pack_size_ml    INTEGER
  unit_price      INTEGER
  store_id        TEXT
  store_name      TEXT
  region          TEXT    -- North, South, East, West
  city            TEXT
  store_format    TEXT    -- Hypermarket, Convenience, Supermarket, Wholesale
  opening_stock   INTEGER
  units_received  INTEGER
  units_sold      INTEGER
  closing_stock   INTEGER
  stockout_flag   BOOLEAN -- 1 = stockout occurred
  revenue         REAL
  promotion_flag  BOOLEAN -- 1 = promotion running
  promotion_type  TEXT    -- BOGO, Price Cut, Display Feature, Bundle, or NULL
  discount_pct    REAL

STRICT RULES:
- Output ONLY a single SELECT statement inside a ```sql code block.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, PRAGMA.
- For booleans: promotion_flag = 1 or stockout_flag = 1
- Always alias aggregates: SUM(revenue) AS total_revenue
- Add LIMIT when listing rows (max 100).
- No explanation, no preamble — ONLY the ```sql block.
"""

SUMMARISE_PROMPT = """
You are a concise FMCG business analyst.
Summarise the SQL query results in 2-4 clear sentences with specific numbers.
Never mention SQL, table names, or column names.
Sound like a business report, not a technical document.
"""

def extract_sql(text):
    m = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m: return m.group(1).strip()
    m = re.search(r"```(.*?)```", text, re.DOTALL)
    if m: return m.group(1).strip()
    # fallback — return as-is if it starts with SELECT
    if text.strip().lower().startswith("select"):
        return text.strip()
    return ""

def is_safe(sql):
    s = sql.strip().lower()
    if not s.startswith("select"): return False
    for kw in ["insert","update","delete","drop","alter","create","attach","pragma"]:
        if re.search(rf"\b{kw}\b", s): return False
    return True

def run_question(question, api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")
    conn = get_db()

    # Step 1 — Generate SQL
    sql_prompt = f"{SCHEMA}\n\nConvert this business question to a SQLite SELECT query:\n{question}"
    sql_response = model.generate_content(sql_prompt)
    sql = extract_sql(sql_response.text)

    if not sql:
        return None, "", "Could not generate a SQL query for that question. Try rephrasing."

    # Step 2 — Safety check
    if not is_safe(sql):
        return None, sql, "Generated query was rejected for safety. Try a different question."

    # Step 3 — Run query
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchmany(200)]
    except Exception as e:
        return None, sql, f"SQL error: {e}. Try rephrasing your question."

    if not rows:
        return [], sql, "No data found for your question. Try adjusting filters like region, category, or date range."

    # Step 4 — Summarise
    summary_prompt = f"{SUMMARISE_PROMPT}\n\nQuestion: {question}\nResults: {json.dumps(rows[:30], default=str)}"
    summary_response = model.generate_content(summary_prompt)
    return rows, sql, summary_response.text

# ── Session state ────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending" not in st.session_state:
    st.session_state.pending = ""

# ── Suggestion chips ─────────────────────────────────────────────────────
suggestions = [
    "Which region had highest revenue?",
    "Top 5 products by units sold?",
    "Promotions vs non-promo sales?",
    "Store with most stockouts?",
    "Revenue by category?",
    "Best brand in West region?",
]
cols = st.columns(3)
for i, s in enumerate(suggestions):
    if cols[i % 3].button(s, key=f"s{i}", use_container_width=True):
        st.session_state.pending = s

st.markdown("---")

# ── Chat history ─────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    if msg["role"] == "user":
        st.markdown(f'<div class="user-msg">🧑‍💼 {msg["content"]}</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="answer-box">🤖 {msg["answer"]}</div>', unsafe_allow_html=True)
        if msg.get("sql"):
            with st.expander("🔍 View SQL query"):
                st.markdown(f'<div class="sql-box">{msg["sql"]}</div>', unsafe_allow_html=True)
        if msg.get("rows"):
            with st.expander(f"📊 View data ({len(msg['rows'])} rows)"):
                st.dataframe(pd.DataFrame(msg["rows"]), use_container_width=True)

# ── Input ────────────────────────────────────────────────────────────────
question = st.chat_input("Ask a question about your FMCG data...")
active = st.session_state.pending or question
if st.session_state.pending:
    st.session_state.pending = ""

if active:
    if not api_key:
        st.warning("⚠️ Enter your Gemini API key in the sidebar first. Get one free at aistudio.google.com")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": active})

    with st.spinner("🔍 Generating SQL and analysing data..."):
        try:
            rows, sql, answer = run_question(active, api_key)
        except Exception as e:
            rows, sql, answer = [], "", f"Something went wrong: {e}"

    st.session_state.messages.append({
        "role": "bot",
        "answer": answer,
        "sql": sql,
        "rows": rows or []
    })
    st.rerun()
