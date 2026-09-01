
---

### File: `AGENTS.md`

```markdown
# Project: samadhan-ai (SIH26-S02)
# AI-Based Citizen Grievance Classification, Prioritization & Duplicate Detection Engine

## 1. System Overview & Directives
You are a senior full-stack AI engineer. You are building `samadhan-ai` for the Smart India Hackathon (SIH26-S02).
- **Core Philosophy:** Hyper-fast, lightweight, server-driven UI. 
- **Strict Constraint:** Do NOT introduce Node.js, NPM, Vite, React, or frontend bundlers. All UI is handled via server-rendered HTML fragments using FastAPI, Jinja2, HTMX, TailwindCSS (via CDN), and Leaflet.js (via CDN).
- **LLM Provider:** NVIDIA NIM / OpenAI-compatible endpoint (`https://integrate.api.nvidia.com/v1`).

---

## 2. Directory Structure
Ensure the project conforms strictly to the following layout:

```text
samadhan-ai/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI server & route definitions
│   ├── database.py          # SQLite engine, session, and ORM models
│   ├── ai_service.py        # NVIDIA API calls (categorization) & embeddings (duplicates)
│   ├── seed_data.py         # Mock dataset for instant hackathon demonstration
│   └── templates/
│       ├── base.html        # Master shell (Tailwind CDN, HTMX, Leaflet scripts)
│       ├── index.html       # Single Page layout with Tab controller
│       └── partials/
│           ├── grievance_card.html   # Complaint card fragment for live stream
│           ├── metrics_panel.html    # Analytics counter cards
│           └── duplicate_modal.html  # Duplicate warning alert fragment
├── .env                     # NVIDIA_API_KEY, NVIDIA_BASE_URL, MODEL_NAME
├── requirements.txt
└── AGENTS.md

```

---

## 3. Tech Stack & Dependencies

Add the following to `requirements.txt`:

```txt
fastapi>=0.110.0
uvicorn[standard]>=0.28.0
jinja2>=3.1.3
python-multipart>=0.0.9
pydantic>=2.6.0
sqlalchemy>=2.0.28
openai>=1.14.0
sentence-transformers>=2.6.0
numpy>=1.26.0
python-dotenv>=1.0.1

```

---

## 4. Environment Variables (`.env`)

```ini
NVIDIA_API_KEY="nvapi-your-key-here"
NVIDIA_BASE_URL="[https://integrate.api.nvidia.com/v1](https://integrate.api.nvidia.com/v1)"
NVIDIA_MODEL="nvidia/llama-3.1-nemotron-70b-instruct"
PORT=8000

```

---

## 5. Database Schema (`app/database.py`)

Use SQLite via SQLAlchemy. Define a table named `complaints`:

| Field Name | Type | Description |
| --- | --- | --- |
| `id` | `Integer`, PK, autoincrement | Unique complaint identifier. |
| `raw_text` | `Text`, nullable=False | Original complaint text (English, Hindi, or Hinglish). |
| `normalized_text` | `Text` | English translation/clean summary produced by LLM. |
| `department` | `String(64)` | Assigned department (e.g., Roads & Potholes, Water Supply, Sanitation, Electricity, Public Safety). |
| `priority` | `String(16)` | `Critical`, `High`, `Medium`, or `Low`. |
| `urgency_score` | `Integer` | Integer score (1 to 100). |
| `is_duplicate` | `Boolean`, default=False | Flag indicating if this issue is already reported. |
| `parent_cluster_id` | `Integer`, nullable=True | Points to the primary `id` if marked as duplicate. |
| `lat` | `Float`, nullable=False | Coordinates for GIS mapping. |
| `lon` | `Float`, nullable=False | Coordinates for GIS mapping. |
| `status` | `String(32)`, default='Pending' | `Pending`, `In Progress`, or `Resolved`. |
| `embedding` | `Text` | Comma-separated or JSON serialized float array for semantic similarity. |
| `created_at` | `DateTime` | Auto-generated timestamp. |

---

## 6. AI Logic Specifications (`app/ai_service.py`)

### A. Classification & Language Normalization (NVIDIA API)

Use `openai.OpenAI(base_url=NVIDIA_BASE_URL, api_key=NVIDIA_API_KEY)` to invoke the LLM.

* **System Prompt**: Instruct the model to normalize multilingual/Hinglish input, categorize into standard municipal departments, evaluate civic urgency (1-100), and output **ONLY** valid JSON.
* **Strict Output Schema**:

```json
{
  "normalized_text": "Clean English summary of the issue.",
  "department": "Roads & Infrastructure | Water Supply | Solid Waste & Sanitation | Electricity & Power | Public Health & Safety",
  "priority": "Critical | High | Medium | Low",
  "urgency_score": 85,
  "action_recommended": "Brief 1-line department dispatch action"
}

```

### B. Duplicate Detection & Clustering (`sentence-transformers`)

* Model: `all-MiniLM-L6-v2` (loaded locally in memory on startup).
* **Cosine Similarity Algorithm**:
1. Compute 384-dimensional vector embedding for `raw_text`.
2. Query all existing records in SQLite and calculate cosine similarity against stored vectors.
3. If $\text{Similarity} \ge 0.82$:
* Flag `is_duplicate = True`.
* Set `parent_cluster_id` to the ID of the matched complaint.


4. If $\text{Similarity} < 0.82$:
* Set `is_duplicate = False`, `parent_cluster_id = None`.





---

## 7. HTTP Endpoints Specification (`app/main.py`)

1. `GET /`
* Returns the rendered `index.html` dashboard shell.


2. `POST /api/complaints/submit`
* Accepts form parameters: `raw_text`, `lat`, `lon`.
* Runs: (1) Normalization & Classification via NVIDIA API $\rightarrow$ (2) Embedding & Duplicate check $\rightarrow$ (3) DB persist.
* Response: Returns HTMX partial `grievance_card.html` (prepended to complaint list) with an HTMX trigger header `HX-Trigger: refreshMap, updateMetrics`.


3. `GET /api/dashboard/metrics`
* Returns HTMX partial `metrics_panel.html` containing: Total Complaints, Resolved %, Duplicate % eliminated, High/Critical count.


4. `GET /api/dashboard/map-points`
* Returns a raw JSON array of complaints: `[{ id, lat, lon, priority, department, is_duplicate }]` for Leaflet.js to render.


5. `PATCH /api/complaints/{id}/status`
* Accepts status update (`In Progress`, `Resolved`) and returns updated card fragment.



---

## 8. UI/UX Rules & Styling (`templates/`)

* **Design Aesthetic:** Dark civic-tech theme. Deep slate background (`bg-slate-900`), borders in `border-slate-800`, cards in `bg-slate-800/80`, sharp typography with Tailwind CSS.
* **Priority Badge Colors:**
* `Critical`: `bg-red-500/20 text-red-400 border border-red-500/40`
* `High`: `bg-orange-500/20 text-orange-400 border border-orange-500/40`
* `Medium`: `bg-amber-500/20 text-amber-400 border border-amber-500/40`
* `Low`: `bg-emerald-500/20 text-emerald-400 border border-emerald-500/40`


* **Duplicate Badge:** `bg-purple-500/20 text-purple-300 border border-purple-500/40` with an icon indicating clustered issue.
* **GIS Map View:** Injects Leaflet.js. Includes a toggle to "Hide/Show Duplicate Clusters" and dynamically applies pulsing red markers to `Critical` priority coordinates.

---

## 9. Mock Seed Script (`app/seed_data.py`)

Create a seed script containing 15 realistic citizen complaints (including 3-4 intentional duplicates, mixed Hinglish/English, and realistic coordinates) to seed the database upon startup if empty.

---

## 10. Execution Sequence for Agent

1. **Initialize Project:** Create directories, virtual environment, and write `requirements.txt`.
2. **Database & Models:** Implement `app/database.py`.
3. **AI Logic Engine:** Implement `app/ai_service.py` with mock fallbacks if the API key is missing.
4. **Seed Script:** Implement `app/seed_data.py` to populate realistic data immediately.
5. **Endpoints & Templates:** Implement `app/main.py` and all HTML partials with Leaflet & HTMX integrations.
6. **Self-Test:** Execute `uvicorn app.main:app --reload` and verify `/` loads without JS errors or broken partials.

```

---