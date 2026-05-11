# Architecture

## System Overview

```
User (LINE App)
    │
    │  HTTPS Webhook
    ▼
LINE Platform
    │
    │  POST /webhook
    ▼
FastAPI (Cloud Run)
    ├─── handle_text_message ──────────────────► Gemini File Search (query)
    ├─── handle_image_message ─► GCS (store) ─► Quick Reply to user
    ├─── handle_file_message ──► GCS (store) ─► Quick Reply to user
    └─── handle_postback
              ├── action=store ─► Background Task ─► Gemini File Search (index) ─► Push notify
              └── action=search ─► GCS (load) ──────► Gemini File Search (query) ─► Reply
```

## Components

### FastAPI (`app/main.py`)
- Handles LINE webhook signature verification
- Routes events to handlers
- Manages FastAPI BackgroundTasks for async indexing

### Session Store (`app/session.py`)
- In-memory dict with 5-minute TTL
- Stores pending file info between upload and user choice
- **Production note**: Replace with Firestore for multi-instance Cloud Run

### Gemini Service (`app/gemini_service.py`)
- `get_or_create_store()` — creates/loads File Search Store (name persisted in GCS)
- `upload_and_index()` — uploads file to File Search Store, polls until indexed
- `query_with_text()` — async RAG query using text
- `query_with_image()` — async RAG query using image (with text fallback)

### LINE Handler (`app/line_handler.py`)
- Downloads content from LINE CDN
- Saves to GCS for persistence
- Dispatches to gemini_service based on user action

## Key Design Decisions

### Gemini File Search Store vs. Custom Vector DB
Using managed `file_search_stores` API means:
- Google handles chunking, embedding (gemini-embedding-2), indexing
- Multimodal by default (text + images in same embedding space)
- No self-managed vector database needed
- Store persists independently of the application

### File Storage (GCS)
- All uploaded files saved to GCS before processing
- Required because: LINE CDN URLs expire, and indexing is async
- Path pattern: `uploads/{user_id}/{message_id}.{ext}`
- Store name persisted at: `config/file_search_store_name.txt`

### Async Indexing (BackgroundTasks)
Gemini File Search upload can take 30s–5min for large files.
- Reply token expires in 30s → cannot wait in the request
- Solution: reply immediately, index in background, push notification when done

### Image Search (with Fallback)
Primary: Pass image bytes directly to generate_content with file_search tool.
Fallback: If primary fails, use Gemini Vision to describe image → text query.

## Data Flow: Store Image

```
1. User sends image
2. LINE → POST /webhook (ImageMessageContent)
3. Download image bytes from LINE CDN
4. Upload to GCS: uploads/{user_id}/{msg_id}.jpg
5. Store GCS path in session
6. Reply: "🖼️ 收到圖片！請問要：" + Quick Reply buttons
7. User taps "📥 存入資料庫"
8. POST /webhook (PostbackEvent action=store)
9. Reply: "⏳ 正在建立索引..."
10. BackgroundTask starts:
    a. Download file_bytes from GCS
    b. Write to temp file
    c. client.file_search_stores.upload_to_file_search_store(...)
    d. Poll operation until done (max 5 min)
    e. Push: "✅ 已成功存入資料庫！"
```

## Data Flow: Text Query

```
1. User sends text
2. LINE → POST /webhook (TextMessageContent)
3. client.aio.models.generate_content(
       model=GEN_MODEL,
       contents=text,
       config=GenerateContentConfig(
           tools=[Tool(file_search=FileSearch(file_search_store_names=[store]))]
       )
   )
4. Gemini embeds query, searches store, retrieves chunks, generates answer
5. Reply with answer
```

## Scaling Notes

| Component | Current (PoC) | Production Recommendation |
|-----------|--------------|--------------------------|
| Session store | In-memory (min-instances=1) | Cloud Firestore |
| File Search Store | Single shared store | Per-tenant stores with metadata filtering |
| Cloud Run instances | min=1 (session) | Firestore allows min=0 |
