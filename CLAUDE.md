# Project Context for Claude Code

This file is read on every Claude Code session in this directory. It captures
project state, design decisions, and gotchas that aren't obvious from the code.

## What this project is

LINE Bot that integrates **Gemini File Search API** for multimodal RAG.
Users upload files/images to LINE → Bot indexes into Gemini File Search Store →
Users query via text or image, get answers grounded in their own documents.

Deployment target: **GCP Cloud Run** (via Cloud Build).

## Important design decisions (don't undo without asking)

### 1. Use Gemini File Search Store, not a custom vector DB
We use the **managed** `client.file_search_stores` API. Google handles chunking,
embedding (gemini-embedding-2), and indexing. Do NOT add ChromaDB / FAISS /
pgvector / etc. — that defeats the point.

### 2. Single shared store + metadata filtering for multi-tenancy
All users share ONE File Search Store. Per-user isolation is via:
- Upload: `custom_metadata: [{"key": "user_id", "string_value": <LINE UID>}]`
- Query: `metadata_filter='user_id="<LINE UID>"'`

The filter is enforced **server-side** by Gemini. Do NOT switch to per-user
stores unless quota becomes an issue — managing N stores is operational pain.

### 3. Async indexing via FastAPI BackgroundTasks
LINE reply tokens expire in 30s; indexing takes 30s–5min. So:
- Upload flow: reply immediately ("⏳ 建立索引中…") → background task does upload
  + polling → `push_message` notification when done.
- Search/text flow: synchronous within 30s budget.

### 4. Session store is in-memory with 5-min TTL
Cloud Run is stateless, so this only works with `min-instances=1`. For
production multi-instance scaling, swap to Firestore. The session only holds
"user just uploaded this file, waiting for them to pick store-or-search."

### 5. Files persisted to GCS
- `uploads/{user_id}/{message_id}.{ext}` — user uploads
- `config/file_search_store_name.txt` — the File Search Store name
- LINE CDN URLs expire and we may handle the postback on a different instance.

## Tech stack snapshot

- Python 3.12, FastAPI, uvicorn
- `line-bot-sdk` v3 (async API: `AsyncMessagingApi`, `AsyncMessagingApiBlob`)
- `google-genai` SDK (the NEW one, not `google-generativeai`)
- `google-cloud-storage`
- Default Gemini model: **`gemini-3.1-flash`** (env var `GEMINI_MODEL`)
- Embedding model: `models/gemini-embedding-2` (multimodal)

## Key API call shapes (so you don't have to rediscover)

### Create File Search Store
```python
store = client.file_search_stores.create(config={
    "display_name": "linebot-multimodal-rag",
    "embedding_model": "models/gemini-embedding-2",
})
```

### Upload with user metadata
```python
operation = client.file_search_stores.upload_to_file_search_store(
    file_search_store_name=store.name,
    file=tmp_path,
    config={
        "display_name": filename,
        "custom_metadata": [{"key": "user_id", "string_value": user_id}],
    },
)
# operation is long-running — poll: client.operations.get(operation)
```

### Query with user filter
```python
response = await client.aio.models.generate_content(
    model=GEN_MODEL,
    contents=text,  # or Content(parts=[image_part, text_part])
    config=types.GenerateContentConfig(
        tools=[types.Tool(file_search=types.FileSearch(
            file_search_store_names=[store_name],
            metadata_filter=f'user_id="{user_id}"',  # google.aip.dev/160 filter
        ))],
    ),
)
```

## File map (where to look first)

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI app, webhook endpoint, `/health`, `/store/info` |
| `app/line_handler.py` | LINE event handlers (text/image/file/postback) |
| `app/gemini_service.py` | All Gemini File Search API calls |
| `app/session.py` | In-memory session w/ TTL |
| `spec/architecture.md` | System design + data flows + scaling notes |
| `spec/deployment.md` | GCP setup steps (APIs, IAM, secrets, deploy) |
| `cloudbuild.yaml` | Build → push → deploy to Cloud Run |

## Things NOT yet done (potential next tasks)

- `/store/info` is unauthenticated — protect for production
- Session store still in-memory (need Firestore for min-instances=0)
- No deletion flow — users can't remove their own documents via LINE
- No quota/rate limiting per user
- No support for audio/video (Gemini File Search limitation)
- LINE access token expiry (30 days) — needs rotation or long-lived token

## How to run locally (quick)

```bash
cp .env.example .env  # fill in LINE secrets, GEMINI_API_KEY, GCS_BUCKET
gcloud auth application-default login
uvicorn app.main:app --reload --port 8080
ngrok http 8080  # set webhook URL in LINE Console
```

## How to deploy

```bash
gcloud builds submit --config=cloudbuild.yaml \
  --substitutions=_GCS_BUCKET=<your-bucket>
```

Full setup steps (one-time IAM + secrets): `spec/deployment.md`.

## GitHub remote

`git@github.com:kkdai/linebot-multimodal-rag.git` (branch: `main`)
Commits use **Evan Lin <evan.if.lin@linecorp.com>** identity.
