# LINE Bot Multimodal RAG

LINE Bot 整合 **Gemini File Search API**，讓你透過 LINE 上傳文件或圖片建立知識庫，並用自然語言或圖片搜尋其中的內容。

> **使用者資料隔離**：每位 LINE 使用者只能存取自己上傳的資料，透過 LINE user ID 在 Gemini File Search Store 的 `custom_metadata` + `metadata_filter` 實作。

---

## 功能

| 操作 | 說明 |
|------|------|
| 傳送 **PDF / 文件** | Bot 詢問：存入資料庫 or 作為搜尋 |
| 傳送 **圖片** | Bot 詢問：存入資料庫 or 作為搜尋 |
| 點選 **「📥 存入資料庫」** | 非同步建立索引（含 user_id metadata），完成後推播通知 |
| 點選 **「🔍 作為搜尋」** | 以該圖片 / 文件作為查詢，僅從自己的資料中找相關內容 |
| 輸入 **文字** | 直接對自己的資料庫做語意查詢（RAG） |

### 支援格式
- 圖片：JPG、PNG、WebP 等
- 文件：PDF、TXT、CSV、Markdown 等
- 單檔上限：100 MB（Gemini File Search API 限制）
- 不支援：音訊（mp3、wav）、影片（mp4、mov）

### 搜尋能力
- **文字查文字**：輸入問題 → 找自己上傳的 PDF / 文件中的相關段落
- **圖片查資料庫**：傳圖片 → Gemini 理解圖片內容 → 找自己資料庫中的相關資訊（包含 PDF 內的圖文說明）
- 跨語言：中文查詢英文文件也能運作（gemini-embedding-2 支援 100+ 語言）
- **多租戶隔離**：每位使用者的資料完全分離，透過 `metadata_filter: user_id="U..."` 在查詢時過濾

---

## 參考資料

本專案的功能設計與 API 用法參考以下官方文件：

- [Expanded Gemini API File Search: multimodal RAG](https://blog.google/innovation-and-ai/technology/developers-tools/expanded-gemini-api-file-search-multimodal-rag/) — Google Blog 公告（多模態 RAG、metadata filter、page citations）
- [Gemini Embedding 2 model card](https://deepmind.google/models/gemini/embedding/) — Embedding 模型規格（5 種模態、8192 tokens、可變維度）
- [Multimodal RAG with the Gemini API File Search tool: A Developer Guide](https://dev.to/googleai/multimodal-rag-with-the-gemini-api-file-search-tool-a-developer-guide-5878) — File Search API 完整程式碼範例
- [File Search API documentation](https://ai.google.dev/gemini-api/docs/file-search?hl=zh-tw) — 官方文件（含 metadata filter 語法）

---

## 技術架構

```
LINE App
  │
  │  Webhook (HTTPS)
  ▼
FastAPI (Cloud Run)
  ├─ 文字訊息 ──────────────────► Gemini File Search → 回覆
  ├─ 圖片 / 檔案 ─► GCS 備份 ──► Quick Reply 按鈕
  └─ Postback 按鈕
       ├─ 存入資料庫 ─► Background Task ─► Gemini 建索引 ─► Push 通知
       └─ 作為搜尋 ──► GCS 讀取 ──────► Gemini File Search → 回覆
```

**核心元件：**
- **Gemini File Search API** — 托管式多模態 RAG（Google 處理 chunking、embedding、indexing）
- **Embedding model**：`gemini-embedding-2`（文字 + 圖片同一向量空間）
- **Generation model**：`gemini-3-flash-preview`（可透過環境變數 `GEMINI_MODEL` 調整）
- **GCS**：上傳檔案的持久化儲存 + File Search Store 名稱記錄
- **FastAPI BackgroundTasks**：避免建索引時佔住 LINE reply token（30 秒限制）

---

## 安裝與本機開發

### 環境需求
- Python 3.12+
- GCP 專案（需有 GCS bucket）
- LINE Bot channel（Messaging API）
- Gemini API Key（[Google AI Studio](https://aistudio.google.com)）

### 1. Clone & 安裝依賴

```bash
git clone <your-repo-url>
cd linebot-multimodal-rag

python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 設定環境變數

```bash
cp .env.example .env
```

編輯 `.env`：

```env
LINE_CHANNEL_SECRET=你的_line_channel_secret
LINE_CHANNEL_ACCESS_TOKEN=你的_line_channel_access_token
GEMINI_API_KEY=你的_gemini_api_key
GCS_BUCKET=你的_gcs_bucket_名稱
GEMINI_MODEL=gemini-3-flash-preview
```

| 變數 | 哪裡取得 |
|------|---------|
| `LINE_CHANNEL_SECRET` | LINE Developers Console → Messaging API → Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developers Console → Messaging API → Channel access token |
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) |
| `GCS_BUCKET` | 自行建立的 GCS bucket 名稱 |

### 3. GCS Bucket 建立（若尚未建立）

```bash
gsutil mb -l asia-east1 gs://你的-bucket-名稱
```

### 4. GCP 認證（本機開發）

```bash
gcloud auth application-default login
```

### 5. 啟動本機伺服器

```bash
uvicorn app.main:app --reload --port 8080
```

啟動成功後會看到：
```
[Startup] File Search Store ready: fileSearchStores/xxxxxxxx
```

### 6. 對外暴露 Webhook（ngrok）

```bash
# 安裝 ngrok: https://ngrok.com
ngrok http 8080
```

取得 `https://xxxx.ngrok.io`，填入 LINE Developers Console：
- Messaging API → Webhook URL → `https://xxxx.ngrok.io/webhook`
- 開啟「Use webhook」

### 7. 確認運作

```bash
# 健康檢查
curl http://localhost:8080/health

# 查看 File Search Store 狀態（已索引幾份文件）
curl http://localhost:8080/store/info
```

---

## 部署到 GCP Cloud Run

### 快速部署

```bash
# 確認已完成 spec/deployment.md 的 Step 1–5
gcloud builds submit \
  --config=cloudbuild.yaml \
  --substitutions=_GCS_BUCKET=你的-bucket-名稱
```

### 取得 Webhook URL

```bash
gcloud run services describe linebot-multimodal-rag \
  --region=asia-east1 \
  --format='value(status.url)'
```

將 `{URL}/webhook` 填入 LINE Developers Console。

詳細步驟見 [spec/deployment.md](spec/deployment.md)。

---

## 如何使用 LINE Bot

### 情境 1：上傳文件建立知識庫

1. 開啟 LINE，找到你的 Bot
2. 點選 **＋** → **檔案** → 選擇 PDF 或文字檔
3. Bot 回覆：「📄 收到檔案：xxx.pdf，請問要：」
4. 點選 **📥 存入資料庫**
5. Bot 回覆：「⏳ 正在建立索引，完成後會通知您...」
6. 等待幾秒到幾分鐘（依檔案大小），Bot 推播：「✅ 已成功存入資料庫！」

### 情境 2：用文字查詢知識庫

1. 直接在聊天框輸入問題，例如：
   - `「第三季的營收是多少？」`
   - `「退換貨政策是什麼？」`
   - `「這個錯誤代碼代表什麼意思？」`
2. Bot 根據已建立的資料庫回答，並引用相關內容

### 情境 3：上傳圖片搜尋相關資料

1. 點選 **＋** → **相簿** → 選擇圖片（例如：截圖、白板照片、產品圖）
2. Bot 回覆：「🖼️ 收到圖片！請問要：」
3. 點選 **🔍 作為搜尋**
4. Bot 分析圖片內容，從資料庫找出相關資訊並回覆

### 情境 4：將圖片也加入資料庫

1. 傳送圖片（如產品照、圖表、截圖）
2. 點選 **📥 存入資料庫**
3. 圖片完成索引後，可以透過文字搜尋這張圖片的相關內容

### 注意事項

- 工作階段有效期 **5 分鐘**：傳送圖片 / 檔案後，需在 5 分鐘內選擇動作
- 若超時請重新上傳
- 所有使用者共用同一個資料庫（PoC 設計）
- 不支援音訊與影片格式

---

## API 端點

| 端點 | 方法 | 說明 |
|------|------|------|
| `/health` | GET | 服務健康檢查 |
| `/store/info` | GET | File Search Store 狀態（文件數、索引狀態） |
| `/webhook` | POST | LINE Bot Webhook 接收端點 |

### `/store/info` 回傳範例

```json
{
  "store_name": "fileSearchStores/abc123",
  "display_name": "linebot-multimodal-rag",
  "embedding_model": "models/gemini-embedding-2",
  "document_count": 5,
  "documents": [
    {
      "name": "fileSearchStores/abc123/documents/def456",
      "display_name": "company_policy.pdf",
      "state": "ACTIVE"
    }
  ]
}
```

---

## 專案結構

```
linebot-multimodal-rag/
├── app/
│   ├── main.py           # FastAPI + webhook routing + /store/info
│   ├── line_handler.py   # LINE 事件處理
│   ├── gemini_service.py # Gemini File Search 封裝
│   └── session.py        # 用戶工作階段（in-memory, 5min TTL）
├── spec/
│   ├── README.md         # 功能說明（精簡版）
│   ├── architecture.md   # 系統架構與資料流詳解
│   └── deployment.md     # GCP 完整部署步驟
├── Dockerfile
├── cloudbuild.yaml       # Cloud Build → Cloud Run 自動部署
├── requirements.txt
├── .env.example
└── README.md             # 本文件
```

---

## 疑難排解

**Bot 沒有回應**
- 確認 Webhook URL 正確填入 LINE Developers Console
- 確認「Use webhook」已開啟
- 檢查 `/health` 是否正常回應

**「工作階段已過期」**
- 傳送圖片 / 檔案後需在 5 分鐘內點選按鈕
- 重新傳送檔案即可

**存入資料庫沒有收到完成通知**
- 大型 PDF 可能需要幾分鐘
- 確認 `LINE_CHANNEL_ACCESS_TOKEN` 有效（有效期限 30 天，需定期更新或設為長期）
- 查看 Cloud Run logs 確認是否有錯誤

**搜尋結果不相關**
- 確認相關文件已成功存入（`/store/info` 確認 state 為 ACTIVE）
- 嘗試更具體的問題描述
- 若為英文文件，中文查詢仍可運作（跨語言 embedding）
