import os
import time
import asyncio
import tempfile
import mimetypes
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from google import genai
from google.genai import types
from google.cloud import storage as gcs

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
GEN_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

STORE_NAME_BLOB = "config/file_search_store_name.txt"
SYSTEM_PROMPT = (
    "你是一個智慧助理，根據資料庫內容回答問題。"
    "請用繁體中文回答，並盡量引用具體資料內容。"
    "若資料庫中沒有足夠資訊，請如實告知並給出最佳建議。"
)

_client: Optional[genai.Client] = None
_store_name: str = ""
_executor = ThreadPoolExecutor(max_workers=4)


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


# --- File Search Store Management ---

def _load_store_name_from_gcs() -> str:
    if not GCS_BUCKET:
        return ""
    try:
        client = gcs.Client()
        blob = client.bucket(GCS_BUCKET).blob(STORE_NAME_BLOB)
        if blob.exists():
            return blob.download_as_text().strip()
    except Exception as e:
        print(f"[GCS] Load store name error: {e}")
    return ""


def _save_store_name_to_gcs(name: str) -> None:
    if not GCS_BUCKET:
        return
    try:
        client = gcs.Client()
        client.bucket(GCS_BUCKET).blob(STORE_NAME_BLOB).upload_from_string(name)
    except Exception as e:
        print(f"[GCS] Save store name error: {e}")


def get_or_create_store() -> str:
    """Get existing File Search Store name or create a new one. Cached in memory."""
    global _store_name
    if _store_name:
        return _store_name

    stored = _load_store_name_from_gcs()
    if stored:
        _store_name = stored
        print(f"[Store] Loaded existing store: {_store_name}")
        return _store_name

    client = get_client()
    store = client.file_search_stores.create(
        config={
            "display_name": "linebot-multimodal-rag",
            "embedding_model": "models/gemini-embedding-2",
        }
    )
    _store_name = store.name
    _save_store_name_to_gcs(_store_name)
    print(f"[Store] Created new store: {_store_name}")
    return _store_name


# --- Upload & Index ---

def _upload_and_index_sync(
    file_bytes: bytes,
    mime_type: str,
    display_name: str,
    custom_metadata: Optional[list[dict]] = None,
) -> None:
    """Blocking: upload file to File Search Store and poll until indexed."""
    client = get_client()
    store_name = get_or_create_store()

    suffix = mimetypes.guess_extension(mime_type) or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        config: dict = {"display_name": display_name}
        if custom_metadata:
            config["custom_metadata"] = custom_metadata

        operation = client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=store_name,
            file=tmp_path,
            config=config,
        )

        # Poll until done (max 5 minutes)
        for _ in range(60):
            if operation.done:
                return
            time.sleep(5)
            operation = client.operations.get(operation)

        if not operation.done:
            raise TimeoutError("Indexing timed out after 5 minutes")
    finally:
        os.unlink(tmp_path)


async def upload_and_index(
    file_bytes: bytes,
    mime_type: str,
    display_name: str,
    custom_metadata: Optional[list[dict]] = None,
) -> None:
    """Async wrapper for upload_and_index_sync."""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        _executor,
        _upload_and_index_sync,
        file_bytes,
        mime_type,
        display_name,
        custom_metadata,
    )


# --- Query ---

async def query_with_text(text: str) -> str:
    """RAG query using text input."""
    store_name = get_or_create_store()

    response = await get_client().aio.models.generate_content(
        model=GEN_MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[
                types.Tool(
                    file_search=types.FileSearch(
                        file_search_store_names=[store_name]
                    )
                )
            ],
        ),
    )
    return response.text


async def query_with_image(image_bytes: bytes, mime_type: str) -> str:
    """RAG query using an image as input — model sees the image and searches the store."""
    store_name = get_or_create_store()

    try:
        response = await get_client().aio.models.generate_content(
            model=GEN_MODEL,
            contents=types.Content(
                parts=[
                    types.Part(
                        inline_data=types.Blob(mime_type=mime_type, data=image_bytes)
                    ),
                    types.Part(
                        text=(
                            "請根據這張圖片的內容，從資料庫中找出相關資訊，"
                            "並提供詳細的分析與說明。請用繁體中文回答。"
                        )
                    ),
                ]
            ),
            config=types.GenerateContentConfig(
                tools=[
                    types.Tool(
                        file_search=types.FileSearch(
                            file_search_store_names=[store_name]
                        )
                    )
                ],
            ),
        )
        return response.text
    except Exception:
        # Fallback: describe image first, then text search
        desc_response = await get_client().aio.models.generate_content(
            model=GEN_MODEL,
            contents=types.Content(
                parts=[
                    types.Part(
                        inline_data=types.Blob(mime_type=mime_type, data=image_bytes)
                    ),
                    types.Part(
                        text="請詳細描述這張圖片的所有重要內容，包括文字、圖形、物件等。"
                    ),
                ]
            ),
        )
        description = desc_response.text
        return await query_with_text(
            f"根據以下圖片描述，請從資料庫中找到相關資訊：\n\n{description}"
        )
