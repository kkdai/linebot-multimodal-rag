# LINE Bot Multimodal RAG

LINE Bot 整合 Gemini File Search API，支援圖片、文件上傳與多模態語意搜尋。

## 功能

| 使用者操作 | Bot 行為 |
|-----------|---------|
| 傳送圖片 | 詢問：存入資料庫 or 作為搜尋？ |
| 傳送檔案（PDF、TXT 等） | 詢問：存入資料庫 or 作為搜尋？ |
| 點選「存入資料庫」 | 非同步建立索引，完成後 push 通知 |
| 點選「作為搜尋」 | 以圖片/檔案作為查詢，搜尋 RAG 資料庫 |
| 輸入文字 | 直接對 RAG 資料庫做語意查詢 |

## 不支援格式

- 音訊（audio/*）
- 影片（video/*）

限制來自 Gemini File Search API（max 100MB per file）。

---

## 快速開始（本機開發）

### 1. 安裝依賴

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env 填入以下值：
```

| 變數 | 說明 |
|------|------|
| `LINE_CHANNEL_SECRET` | LINE Bot Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot Channel Access Token |
| `GEMINI_API_KEY` | Google AI Studio API Key |
| `GCS_BUCKET` | GCS bucket 名稱（存放上傳檔案與 store name） |
| `GEMINI_MODEL` | 預設 `gemini-2.0-flash` |

### 3. 啟動本機伺服器

```bash
uvicorn app.main:app --reload --port 8080
```

### 4. 本機 Webhook（使用 ngrok）

```bash
ngrok http 8080
# 將 https://xxx.ngrok.io/webhook 填入 LINE Developers Console
```

---

## 環境準備（GCP）

詳見 [deployment.md](deployment.md)

需要建立：
- GCS Bucket
- Artifact Registry Repository
- Cloud Run Service
- Secret Manager Secrets（LINE_CHANNEL_SECRET、LINE_CHANNEL_ACCESS_TOKEN、GEMINI_API_KEY）

---

## 架構說明

詳見 [architecture.md](architecture.md)
