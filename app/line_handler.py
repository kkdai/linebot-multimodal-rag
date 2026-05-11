import os
import mimetypes
from typing import Optional

from fastapi import BackgroundTasks
from linebot.v3.messaging import (
    AsyncApiClient,
    AsyncMessagingApi,
    AsyncMessagingApiBlob,
    Configuration,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage,
    QuickReply,
    QuickReplyItem,
    PostbackAction,
)
from linebot.v3.webhooks import (
    MessageEvent,
    PostbackEvent,
    TextMessageContent,
    ImageMessageContent,
    FileMessageContent,
)
from google.cloud import storage as gcs

from app.session import session_store
import app.gemini_service as gemini

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")

configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)

# Max file size LINE Bot supports: ~10MB for images, ~50MB for files
MAX_STORE_SIZE_BYTES = 100 * 1024 * 1024  # 100MB (Gemini limit)


# --- Helpers ---

def _choice_quick_reply() -> QuickReply:
    return QuickReply(
        items=[
            QuickReplyItem(
                action=PostbackAction(
                    label="📥 存入資料庫",
                    data="action=store",
                    display_text="存入資料庫",
                )
            ),
            QuickReplyItem(
                action=PostbackAction(
                    label="🔍 作為搜尋",
                    data="action=search",
                    display_text="作為搜尋",
                )
            ),
        ]
    )


async def _reply(
    reply_token: str,
    text: str,
    quick_reply: Optional[QuickReply] = None,
) -> None:
    msg = TextMessage(text=text, quick_reply=quick_reply)
    async with AsyncApiClient(configuration) as api_client:
        api = AsyncMessagingApi(api_client)
        await api.reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[msg])
        )


async def _push(user_id: str, text: str) -> None:
    async with AsyncApiClient(configuration) as api_client:
        api = AsyncMessagingApi(api_client)
        await api.push_message(
            PushMessageRequest(to=user_id, messages=[TextMessage(text=text)])
        )


async def _download_line_content(message_id: str) -> bytes:
    async with AsyncApiClient(configuration) as api_client:
        blob_api = AsyncMessagingApiBlob(api_client)
        content = await blob_api.get_message_content(message_id=message_id)
        return bytes(content)


async def _save_to_gcs(data: bytes, path: str, content_type: str) -> str:
    if not GCS_BUCKET:
        return ""
    client = gcs.Client()
    blob = client.bucket(GCS_BUCKET).blob(path)
    blob.upload_from_string(data, content_type=content_type)
    return f"gs://{GCS_BUCKET}/{path}"


async def _load_from_gcs(path: str) -> bytes:
    client = gcs.Client()
    return client.bucket(GCS_BUCKET).blob(path).download_as_bytes()


# --- Background task ---

async def _bg_store_and_notify(
    user_id: str,
    gcs_path: str,
    mime_type: str,
    display_name: str,
) -> None:
    try:
        file_bytes = await _load_from_gcs(gcs_path)
        await gemini.upload_and_index(file_bytes, mime_type, display_name, user_id)
        await _push(user_id, f"✅ 已成功存入您的資料庫！\n📄 {display_name}")
    except Exception as e:
        print(f"[BG Store] Error: {e}")
        await _push(user_id, f"❌ 存入失敗：{str(e)[:120]}")


# --- Event Handlers ---

async def handle_text_message(event: MessageEvent) -> None:
    text = event.message.text.strip()
    if not text:
        return

    user_id = event.source.user_id

    try:
        answer = await gemini.query_with_text(text, user_id)
    except Exception as e:
        answer = f"❌ 查詢失敗：{str(e)[:120]}"

    await _reply(event.reply_token, answer)


async def handle_image_message(
    event: MessageEvent, background_tasks: BackgroundTasks
) -> None:
    user_id = event.source.user_id
    message_id = event.message.id

    try:
        image_bytes = await _download_line_content(message_id)
        gcs_path = f"uploads/{user_id}/{message_id}.jpg"
        await _save_to_gcs(image_bytes, gcs_path, "image/jpeg")

        session_store.set(user_id, "gcs_path", gcs_path)
        session_store.set(user_id, "mime_type", "image/jpeg")
        session_store.set(user_id, "display_name", f"image_{message_id}.jpg")
        session_store.set(user_id, "content_type", "image")

        await _reply(
            event.reply_token,
            "🖼️ 收到圖片！請問要：",
            _choice_quick_reply(),
        )
    except Exception as e:
        await _reply(event.reply_token, f"❌ 圖片處理失敗：{str(e)[:120]}")


async def handle_file_message(
    event: MessageEvent, background_tasks: BackgroundTasks
) -> None:
    user_id = event.source.user_id
    message_id = event.message.id
    filename = getattr(event.message, "file_name", None) or f"file_{message_id}"

    mime_type, _ = mimetypes.guess_type(filename)
    mime_type = mime_type or "application/octet-stream"
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"

    # Reject unsupported types (Gemini File Search limitation)
    unsupported = ("audio/", "video/")
    if any(mime_type.startswith(u) for u in unsupported):
        await _reply(
            event.reply_token,
            f"⚠️ 目前不支援音訊/影片檔案。\n"
            f"支援格式：PDF、圖片、TXT、CSV 等文字/文件類型。",
        )
        return

    try:
        file_bytes = await _download_line_content(message_id)
        gcs_path = f"uploads/{user_id}/{message_id}.{ext}"
        await _save_to_gcs(file_bytes, gcs_path, mime_type)

        session_store.set(user_id, "gcs_path", gcs_path)
        session_store.set(user_id, "mime_type", mime_type)
        session_store.set(user_id, "display_name", filename)
        session_store.set(user_id, "content_type", "file")

        await _reply(
            event.reply_token,
            f"📄 收到檔案：{filename}\n請問要：",
            _choice_quick_reply(),
        )
    except Exception as e:
        await _reply(event.reply_token, f"❌ 檔案處理失敗：{str(e)[:120]}")


async def handle_postback(
    event: PostbackEvent, background_tasks: BackgroundTasks
) -> None:
    user_id = event.source.user_id
    action = event.postback.data

    gcs_path = session_store.get(user_id, "gcs_path")
    mime_type = session_store.get(user_id, "mime_type")
    display_name = session_store.get(user_id, "display_name")
    content_type = session_store.get(user_id, "content_type")

    if not gcs_path:
        await _reply(
            event.reply_token,
            "⚠️ 工作階段已過期（5 分鐘），請重新上傳檔案。",
        )
        return

    session_store.clear(user_id)

    if action == "action=store":
        await _reply(
            event.reply_token,
            f"⏳ 正在建立索引，完成後會通知您...\n📄 {display_name}",
        )
        background_tasks.add_task(
            _bg_store_and_notify, user_id, gcs_path, mime_type, display_name
        )

    elif action == "action=search":
        try:
            file_bytes = await _load_from_gcs(gcs_path)

            if content_type == "image":
                answer = await gemini.query_with_image(file_bytes, mime_type, user_id)
            else:
                # Non-image file: query by filename as hint
                answer = await gemini.query_with_text(
                    f"請從資料庫中找到與《{display_name}》相關的資訊並說明。",
                    user_id,
                )

            await _reply(event.reply_token, answer)
        except Exception as e:
            await _reply(event.reply_token, f"❌ 搜尋失敗：{str(e)[:120]}")
