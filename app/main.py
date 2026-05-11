import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from linebot.v3 import WebhookParser
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import (
    FileMessageContent,
    ImageMessageContent,
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
)

import app.gemini_service as gemini
from app import line_handler

app = FastAPI(title="LINE Bot Multimodal RAG")
parser = WebhookParser(os.environ.get("LINE_CHANNEL_SECRET", ""))


@app.on_event("startup")
async def startup() -> None:
    loop = asyncio.get_event_loop()
    try:
        store = await loop.run_in_executor(None, gemini.get_or_create_store)
        print(f"[Startup] File Search Store ready: {store}")
    except Exception as e:
        print(f"[Startup] Warning: Could not initialize store: {e}")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "store": gemini._store_name or "not initialized"}


@app.get("/store/info")
async def store_info() -> dict:
    loop = asyncio.get_event_loop()
    try:
        store_name = await loop.run_in_executor(None, gemini.get_or_create_store)
        client = gemini.get_client()
        store = await loop.run_in_executor(
            None, lambda: client.file_search_stores.get(name=store_name)
        )
        documents = await loop.run_in_executor(
            None,
            lambda: list(client.file_search_stores.documents.list(parent=store_name)),
        )
        return {
            "store_name": store_name,
            "display_name": getattr(store, "display_name", ""),
            "embedding_model": getattr(store, "embedding_model", ""),
            "document_count": len(documents),
            "documents": [
                {
                    "name": getattr(d, "name", ""),
                    "display_name": getattr(d, "display_name", ""),
                    "state": str(getattr(d, "state", "")),
                }
                for d in documents
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks) -> str:
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()

    try:
        events = parser.parse(body.decode("utf-8"), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    for event in events:
        if isinstance(event, MessageEvent):
            if isinstance(event.message, TextMessageContent):
                await line_handler.handle_text_message(event)
            elif isinstance(event.message, ImageMessageContent):
                await line_handler.handle_image_message(event, background_tasks)
            elif isinstance(event.message, FileMessageContent):
                await line_handler.handle_file_message(event, background_tasks)
        elif isinstance(event, PostbackEvent):
            await line_handler.handle_postback(event, background_tasks)

    return "OK"
