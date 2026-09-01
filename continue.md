# samadhan-ai — Continue Here

> **Project:** samadhan-ai (SIH26-S02) — AI-Based Citizen Grievance Classification, Prioritization & Duplicate Detection Engine  
> **Branch:** `main` · **Repo:** https://github.com/The-Shreyas-M/samadhan-ai

---

## 1. Setup (one-time)

```powershell
cd C:\Users\shrey_itz95ac\Projects\samadhan-ai

# Create venv (skip if already exists)
python -m venv venv

# Install deps
.\venv\Scripts\pip install -r requirements.txt

# Copy env file and fill in real NVIDIA API key
copy .env.example .env   # if it doesn't exist, create it manually
```

### `.env` required contents
```ini
NVIDIA_API_KEY="nvapi-your-key-here"
NVIDIA_BASE_URL="https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL="nvidia/nemotron-3-super-120b-a12b"
VISION_MODEL="nvidia/neva-22b"
SECRET_KEY="samadhan-dev-secret"
PORT=8000
```

### Run the server
```powershell
# From project root
.\venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Then open `http://127.0.0.1:8000` in a browser (Chrome/Edge works best; the camera API requires HTTPS or localhost).

> **Note:** The server must be started with `--reload` (or restarted) whenever any `.py` file changes. Templates (`.html`) are re-read on each request, so no restart needed for HTML-only changes.

### Verify the app is alive
```
GET /              → index.html (citizen portal)
GET /login         → login page
GET /admin         → admin dashboard (requires login as admin)
GET /dept/police   → police dept dashboard
GET /api/dashboard/categories → JSON list of complaint categories
```

### Login credentials (seeded on first run)
- Admin: `admin` / `admin123`
- Each dept officer: `<key>` / `<key>123` (e.g. `police` / `police123`, `fire` / `fire123`, `water` / `water123`, `roads` / `roads123`, etc.)

---

## 2. Tech Stack

- **Backend:** FastAPI + Jinja2 + SQLAlchemy (SQLite) + python-dotenv
- **Frontend:** HTMX 1.9.12 + Tailwind CSS (CDN) + Leaflet.js 1.9.4 (CDN) + Chart.js 4.4.4 (CDN) + piexifjs (CDN)
- **AI:** NVIDIA NIM OpenAI-compatible client (`openai` pip package)
- **Auth:** Starlette SessionMiddleware (cookie-based, `itsdangerous` signed)
- **No frontend bundlers allowed** (no Node/Vite/React/etc.)

---

## 3. Architecture at a Glance

```
app/
├── main.py            # All FastAPI routes + templates + business logic
├── database.py        # SQLAlchemy models (User, Complaint)
├── ai_service.py      # LLM classification + embeddings + duplicate detection
├── departments.py     # 12-department registry
├── seed_data.py       # 15 seed complaints + admin+dept officer users
├── evidence.py        # save_photo, save_photo_base64, extract_exif
├── spam.py            # Rate limit + spam detection + geotag verification
├── vision.py          # LLM vision verify + AI-generated image heuristic
├── auth.py            # get_current_user, require_auth, require_admin
└── templates/
    ├── base.html          # Master shell (CDN scripts)
    ├── index.html         # CITIZEN form (analyse→submit flow, pin map, camera)
    ├── login.html
    ├── track.html
    ├── admin.html         # ADMIN dashboard (charts + all-filters map + list)
    ├── dept.html          # DEPT dashboard (own-dept map + filters + list)
    └── partials/
            ├── complaint_card.html   # Single complaint card (photo view via openCardPhoto)
            ├── complaint_list.html   # List of cards
            ├── submit_result.html    # Post-submit feedback + tracking ID
            ├── dept_tiles.html
            ├── dept_stats.html
```

### Key routes
| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Citizen portal |
| GET/POST | `/login` | Login |
| GET | `/logout` | Logout |
| GET | `/track` or `/track/{id}` | Track a complaint |
| POST | `/api/complaints/submit` | Submit complaint (htmx) |
| POST | `/api/complaints/analyze` | Analyse only (no persist) |
| PATCH | `/api/complaints/{id}/status` | Update status |
| GET | `/api/dashboard/admin-list` | Admin filtered complaint list |
| GET | `/api/dashboard/dept-map-points?key=X` | Dept map markers |
| GET | `/api/dashboard/admin-map-points` | Admin map markers (all filters) |
| GET | `/api/dashboard/categories` | Distinct complaint categories |
| GET | `/api/dashboard/chart-data` | Chart.js JSON |
| GET | `/admin` | Admin dashboard |
| GET | `/dept/{key}` | Dept dashboard |

---

## 4. What's Been Implemented

### ✅ Citizen portal (`index.html`)
- **Analyse-first flow:** user types complaint → clicks "🔍 Analyse Complaint" → AI returns department/priority/urgency/category → Submit button enables.
- **Camera only for Critical/High:** camera widget is hidden unless AI classifies as Critical or High.
- **Pin-placement map** (Leaflet) with **place search** (Nominatim geocoding).
- **GPS enforcement for Critical/High:** manual pin click is disabled when priority is Critical/High; user is forced to use "📡 Use My Location".
- **Loading states:** analyse button and submit button both show spinners + disable on click (prevents double-submit).
- **Tracking ID shown** after successful submit (in `partials/submit_result.html`).

### ✅ Admin dashboard (`admin.html`)
- Department tile KPIs, 3 Chart.js charts.
- **Full GIS map** respecting all filters: department, status, priority, **classification (category)**, flagged.
- **Place search** (Nominatim) to jump the admin map to any location.
- Filters drive both map and list simultaneously.
- **Photo viewing:** clicking a marker's photo or a card's "View 🔍" opens a lightbox via `openCardPhoto()` / `openPhotoModal()` (global functions in `base.html`).

### ✅ Dept dashboard (`dept.html`)
- Department KPI cards, **own-dept map** with dept-key pre-set.
- Filters: status, priority, classification (all drive map + list).
- Same search + photo-viewing capabilities.

### ✅ Backend
- `POST /api/complaints/analyze` — classification only, returns `requires_photo` flag.
- Filtered map-point endpoints for admin + dept (authorizes dept access).
- `photo_url()` Jinja filter + `_point_json()` helper for consistent photo URLs.
- Category endpoint, chart-data endpoint.
- Photo stored as base64 JPEG with injected GPS+timestamp EXIF.

---

## 5. Known Bugs (DO NOT FIX — just document)

The following issues are present in the current running build (visible in server logs). **Fix them in a separate session, do not change any code yet.**

### Bug 1 — Double `uploads/` in photo URLs (404)
```
GET /uploads/uploads/3b0e965a27694cd8bf3e9725409d947a.jpg → 404
```
The `photo_url()` Jinja filter or how `photo_path` is stored causes the `/uploads/` prefix to be doubled. Static files (`app.mount("/uploads", StaticFiles(directory="uploads")...)`) serve files from `uploads/`, but the URLs generated point to `/uploads/uploads/...`.  
**Fix:** Ensure either (a) `photo_path` is stored as just the filename (not `uploads/fname`), or (b) the template/base URL strips the leading `uploads/`. Check `evidence.py:save_photo_base64` return value and `main.py:photo_url()`.

### Bug 2 — 422 on `PATCH /api/complaints/{id}/status`
```
PATCH /api/complaints/18/status → 422 Unprocessable Entity
```
The status `<select>` in `partials/complaint_card.html` is missing `name="status"` so HTMX sends no form field and FastAPI validation fails.  
**Fix:** Add `name="status"` to the `<select>` element.

### Bug 3 — Submit button keeps spinning / no redirect to tracking ID
After a successful submit, the `htmx:afterRequest` handler on `index.html` keeps the button disabled and the page never navigates to `/track/{tracking_id}`.  
**Fix:** On `htmx:afterRequest` with `evt.detail.successful`, either redirect (`window.location.href = '/track/{id}'`) or re-enable the button after a delay and ensure `#submit-feedback` becomes visible.

### Bug 4 — Map doesn't refresh after new complaint is submitted
New complaints appear in the list but not on admin/dept maps. The map only loads on `window.load`.  
**Fix:** After a successful submit, trigger `refreshMap` event (already dispatched from the citizen form) and make admin/dept maps listen for it and reload their markers.

### Bug 5 — "View image" doesn't work in dept/admin views
Related to Bug 1 — the broken photo URL causes image load to fail in both the card thumbnail and the map popup. Fixing Bug 1 should resolve this.

### Bug 6 — "Use My Location" not working
`useGps()` calls `navigator.geolocation.getCurrentPosition` but the callback may not fire. Possible causes: browser permission denied, HTTPS requirement, or `enableHighAccuracy` issues. The function logs specific error messages to `#loc-status`.  
**Fix:** Add more robust fallback; check `navigator.geolocation` support; handle `PERMISSION_DENIED` explicitly.

---

## 5.5 IMPORTANT — LLM Classification Was Silently Falling Back to Keywords ✅ FIXED

**Root cause found (this is why department/category always look generic):**

- `.env` sets `NVIDIA_MODEL="nvidia/llama-3.1-nemotron-70b-instruct"`, but that model returns a hard **404** for the account tied to this API key:
  ```
  404 ... Function '9b96341b-...': Not found for account 'tc1fxui...'
  ```
- `classify_complaint()` wraps the LLM call in `try/except` and silently returns `keyword_classify(raw_text)` on any error (`app/ai_service.py`). So **every** classification uses keywords: category always `"General"`, priority fixed at `High`/70 or `Medium`/50, action text `"Dispatch <Dept> team for assessment."`
- **Models verified WORKING for this key** (probed via `/v1/chat/completions` and `/v1/models`):
  - `nvidia/nemotron-3-super-120b-a12b` ✅ (also the code default) — do NOT change this
  - `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` ✅
- **Broken for this key (404):** `nvidia/llama-3.1-nemotron-70b-instruct`, `nvidia/llama3-chatqa-1.5-70b`, `nvidia/nemotron-nano-3-30b-a3b`, `nvidia/nemotron-4-340b-instruct`

**Status: ✅ FIXED & verified 2026-09-01** — `.env` now set to `NVIDIA_MODEL="nvidia/nemotron-3-super-120b-a12b"`; `ai_service.py` logs the real exception on LLM failure, the keyword fallback returns per-department categories + varied urgency/priority, and `_resolve_department` returns roads only when no valid department matches. Verified from a fresh process (health→Critical/95, fire→Critical/90, theft→police/High/70, pothole→roads/Medium/60, bijli→electricity/High/75) and via `/api/complaints/analyze` (TestClient, 200 OK).

**Remaining:** the long-running server must be **restarted** to pick up the new `.env` model + code (it predates the fix and still uses keyword fallback).

---

## 6. What to Implement Next (priority order)

1. **Fix Bug 1** (double `uploads/` in photo URLs) — highest priority, breaks all image viewing
2. **Fix Bug 2** (422 on status update) — blocks officers from updating complaint status
3. **Fix Bug 3** (submit stuck spinning / no redirect) — UX is broken on submit
4. **Fix Bug 4** (map doesn't refresh after submit) — admin/dept maps stale
5. **Fix Bug 6** ("Use My Location") — blocks Critical/High complaints from getting coordinates
6. Add **user feedback** toasts (like a small notification area) for submit success/failure
7. Add **debounce** on the place search input (don't fire Nominatim on every keystroke)
8. Add **offline/empty-state** illustrations when no complaints match filters
9. Consider persisting rate-limit counters to SQLite instead of in-memory dict (survives server restart)

---

## 7. Database

- **File:** `samadhan.db` (SQLite, created on first startup via `init_db()`)
- **Tables:** `user`, `complaint` (see `app/database.py` for schema)
- **Seed data:** 15 complaints + admin + 12 dept officer users, seeded automatically if DB is empty

To inspect the DB:
```powershell
.\venv\Scripts\python
>>> import sqlite3
>>> conn = sqlite3.connect('samadhan.db')
>>> conn.row_factory = sqlite3.Row
>>> for r in conn.execute('SELECT * FROM complaint ORDER BY id DESC LIMIT 5'): print(dict(r))
```

---

## 8. Git Notes

- **Remote:** `origin` → `https://github.com/The-Shreyas-M/samadhan-ai.git`
- **Default branch:** `main`
- **PowerShell compatibility:** This environment uses PowerShell 5.1 which does NOT support `&&`, `||`, `head`, `tail`, or `<<` heredocs. Use separate commands.
- Push with: `git -C "C:\Users\shrey_itz95ac\Projects\samadhan-ai" push origin main`

---

## 9. Quick Verification Checklist

After starting the server, verify these work in order:

1. [ ] `http://127.0.0.1:8000` loads the citizen portal with map
2. [ ] Clicking the map sets a pin (lat/lon inputs populated)
3. [ ] Place search in the citizen form finds a location via Nominatim
4. [ ] "Use My Location" gets the browser geolocation
5. [ ] "🔍 Analyse Complaint" returns classification without persisting
6. [ ] Submit button enables after analysis
7. [ ] Camera appears ONLY for Critical/High priority
8. [ ] Submit shows tracking ID, no infinite spinner
9. [ ] `/admin` login works and shows the map with markers
10. [ ] Admin map markers match the filtered complaint list
11. [ ] Admin map search (Nominatim) pans the map
12. [ ] Clicking a photo opens a lightbox (admin & dept)
13. [ ] Status dropdown in complaint cards updates without 422 error
14. [ ] New complaints appear on the map immediately
15. [ ] Photo URLs return 200 (no double `/uploads/uploads/`)

---

*Last session notes: The `continue.md` itself was written by the AI and pushed to `main`. All source code is up to date in the repo.*
