# FMCG AI Assistant 🥤

A Text-to-SQL AI assistant for FMCG beverages analytics.  
Ask questions in plain English → AI generates SQL → runs on database → plain English answer.

## Tech Stack
- **Backend**: FastAPI + Claude API (Anthropic)
- **Frontend**: Streamlit chat UI
- **Database**: SQLite (built from merged_data.csv)

## Local Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your Anthropic API key
```bash
export ANTHROPIC_API_KEY=your_key_here
```

### 3. Build the database
```bash
python build_db.py
```

### 4. Start the FastAPI backend
```bash
uvicorn main:app --reload --port 8000
```

### 5. Start the Streamlit frontend (new terminal)
```bash
streamlit run app.py
```

Open http://localhost:8501 in your browser.

## Deployment

### Backend → Render
1. Push this repo to GitHub
2. Go to render.com → New Web Service → connect repo
3. Build Command: `pip install -r requirements.txt && python build_db.py`
4. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
5. Add environment variable: `ANTHROPIC_API_KEY = your_key`
6. Make sure `merged_data.csv` is committed to the repo

### Frontend → Streamlit Cloud
1. Go to share.streamlit.io → New app → connect repo
2. Main file: `app.py`
3. Add secret: `API_URL = https://your-render-app.onrender.com`

## Sample Questions
- Which region had the highest revenue?
- Top 5 products by units sold?
- How much did promotions boost sales vs non-promo weeks?
- Which store had the most stockouts?
- Revenue by category breakdown?
- Which brand performs best in the West region?
