import streamlit as st
import sqlite3, json, re, os, tempfile, pandas as pd
from groq import Groq

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

st.markdown('<p class="main-title">🥤 FMCG AI Assistant</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-title">Ask any business question about beverages sales, inventory & promotions.</p>', unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ⚙️ Settings")
    api_key = st.text_input(
        "Groq API Key", type="password",
        value=st.secrets.get("GROQ_API_KEY", ""),
        help="Free key from console.groq.com"
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

@st.cache_resource
def get_db():
    csv_path = os.path.join(os.path.dirname(__file__), "merged_data.csv")
    df = pd.read_csv(csv_path)
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    conn = sqlite3.connect(tmp.name, check_same_thread=False)
    df.to_sql("fmcg_data", conn, if_exists="replace", index=False)
    for col in ["product_id","store_id","week_start_date","region","promotion_flag"]:
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{col} ON fmcg_data({col})")
    conn.commit()
    return conn

SCHEMA = """You are a SQL expert for an FMCG beverages SQLite database.
ONE table called fmcg_data with columns:
  week_start_date TEXT, product_id TEXT, product_name TEXT, brand TEXT,
  category TEXT (Juice/Water/Carbonated/Energy/Dairy),
  pack_size_ml INTEGER, unit_price INTEGER,
  store_id TEXT, store_name TEXT, region TEXT (North/South/East/West),
  city TEXT, store_format TEXT (Hypermarket/Convenience/Supermarket/Wholesale),
  opening_stock INTEGER, units_received INTEGER, units_sold INTEGER,
  closing_stock INTEGER, stockout_flag BOOLEAN (1=stockout),
  revenue REAL, promotion_flag BOOLEAN (1=promotion), promotion_type TEXT, discount_pct REAL

RULES:
- Output ONLY a single SELECT inside a ```sql block. Nothing else.
- Never use INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/PRAGMA.
- Booleans: promotion_flag=1 or stockout_flag=1
- Always alias aggregates: SUM(revenue) AS total_revenue
- Add LIMIT (max 100) when listing rows."""

def extract_sql(text):
    m = re.search(r"```sql\s*(.*?)```", text, re.DOTALL|re.IGNORECASE)
    if m: return m.group(1).strip()
    m = re.search(r"```(.*?)```", text, re.DOTALL)
    if m: return m.group(1).strip()
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
    client = Groq(api_key=api_key)
    conn = get_db()

    # Step 1 — Generate SQL
    r = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SCHEMA},
            {"role": "user", "content": f"Convert to SQLite SELECT:\n{question}"}
        ],
        temperature=0,
        max_tokens=300
    )
    sql = extract_sql(r.choices[0].message.content)

    if not sql:
        return None, "", "Could not generate SQL. Try rephrasing your question."

    if not is_safe(sql):
        return None, sql, "Query rejected for safety. Try a different question."

    # Step 2 — Run query
    try:
        cur = conn.cursor()
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchmany(200)]
    except Exception as e:
        return None, sql, f"SQL error: {e}. Try rephrasing."

    if not rows:
        return [], sql, "No data found. Try adjusting your filters."

    # Step 3 — Summarise
    r2 = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "You are an FMCG business analyst. Summarise results in 2-4 clear sentences with specific numbers. Never mention SQL, tables, or column names."},
            {"role": "user", "content": f"Question: {question}\nResults: {json.dumps(rows[:30], default=str)}\nGive a business summary."}
        ],
        max_tokens=300
    )
    return rows, sql, r2.choices[0].message.content

# Session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending" not in st.session_state:
    st.session_state.pending = ""

# Suggestion chips
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

# Chat history
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

# Input
st.markdown("---")
question = st.chat_input("Ask a question about your FMCG data...")
active = st.session_state.pending or question
if st.session_state.pending:
    st.session_state.pending = ""

if active:
    if not api_key:
        st.warning("⚠️ Enter your Groq API key in the sidebar. Free at console.groq.com")
        st.stop()

    st.session_state.messages.append({"role": "user", "content": active})

    with st.spinner("🔍 Generating SQL and analysing data..."):
        try:
            rows, sql, answer = run_question(active, api_key)
        except Exception as e:
            rows, sql, answer = [], "", f"Error: {e}"

    st.session_state.messages.append({
        "role": "bot", "answer": answer, "sql": sql, "rows": rows or []
    })
    st.rerun()
