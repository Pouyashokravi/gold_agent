# Gold Research Agent

XAU/USD multi-agent research system (**V2 Gold Manager architecture**).

See [`docs/V2_ARCHITECTURE.md`](docs/V2_ARCHITECTURE.md) for the V2 design, migration notes, and deliverables.

## Setup

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
copy ..\.env.example ..\.env   # fill API keys
uvicorn app.main:app --reload --app-dir .

# Frontend
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

## Architecture (V2)

- **Fast path** for simple price/indicator queries (no full research pipeline)
- **Gold Manager** plans, delegates to News/Fundamental/Technical specialists + direct tools in parallel, reviews evidence, replans (bounded), then answers
- **Short-term working memory** reuses fresh quotes/analysis (separate from chat history)
- **Trader Mode**, Economic Surprise, News Impact, and Conflict Matrix are preserved

## API

- `POST /api/conversations` — create conversation
- `POST /api/analyze` — SSE stream
- `GET /api/conversations/{id}` — history
- `GET /health` — health check

## Env

See `.env.example`. Important model vars: `FAST_MODEL`, `MANAGER_MODEL`, `NEWS_MODEL`, `FUNDAMENTAL_MODEL`, `TECHNICAL_MODEL`, `MAX_REPLAN_ROUNDS`.

Set `MOCK_EXTERNAL_APIS=true` for dev without burning API credits.

## Tests

```bash
cd backend
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

## Deploy (Render)

Test deployment uses two Render web services defined in [`render.yaml`](render.yaml):

| Service | URL (default) |
| ------ | --------------- |
| Frontend | `https://gold-agent-web.onrender.com` |
| Backend API | `https://gold-agent-api.onrender.com` |

Share the **frontend URL** with testers.

### One-time setup

1. Push this repo to GitHub (do not commit `.env` or `frontend/.env.local`).
2. Rotate any API keys that were ever committed to `.env.example`.
3. Open [dashboard.render.com](https://dashboard.render.com) → **New → Blueprint** → select the repo.
4. When prompted, enter secret env vars:
   - `OPENAI_API_KEY`
   - `TWELVE_DATA_API_KEY`
   - `FRED_API_KEY`
   - `TAVILY_API_KEY`
5. Wait for both services to deploy. Verify backend health:

   `GET https://gold-agent-api.onrender.com/health`

   Should include `"openai_configured": true` (and other keys). If `false`, add the missing env var on **gold-agent-api** and redeploy.

### Free tier notes for testers

- Services **spin down after 15 minutes** of inactivity; the first request after sleep takes ~1 minute.
- SQLite data is **ephemeral** on free tier (chat history resets on redeploy).
- If the frontend cannot reach the API, confirm `NEXT_PUBLIC_API_URL` and `CORS_ORIGINS` in the Render dashboard, then **rebuild the frontend** (Next.js bakes `NEXT_PUBLIC_*` at build time).

### Alternatives

- **Frontend on Vercel** + backend on Render: set `NEXT_PUBLIC_API_URL` to the Render API URL and add the Vercel origin to `CORS_ORIGINS`.
- **Railway / Fly.io**: better if you need persistent SQLite or no cold starts.
