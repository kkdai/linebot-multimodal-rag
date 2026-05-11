# GCP Deployment Guide

## Prerequisites

- GCP Project with billing enabled
- `gcloud` CLI authenticated
- LINE Bot channel created (LINE Developers Console)
- Google AI Studio API key (https://aistudio.google.com)

---

## Step 1: Enable APIs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com
```

---

## Step 2: Create GCS Bucket

```bash
export PROJECT_ID=$(gcloud config get-value project)
export GCS_BUCKET=linebot-rag-store-${PROJECT_ID}

gsutil mb -l asia-east1 gs://${GCS_BUCKET}
```

---

## Step 3: Create Artifact Registry

```bash
gcloud artifacts repositories create linebot \
  --repository-format=docker \
  --location=asia-east1 \
  --description="LINE Bot images"
```

---

## Step 4: Store Secrets in Secret Manager

```bash
# LINE Channel Secret
echo -n "your_line_channel_secret" | \
  gcloud secrets create LINE_CHANNEL_SECRET --data-file=-

# LINE Channel Access Token
echo -n "your_line_channel_access_token" | \
  gcloud secrets create LINE_CHANNEL_ACCESS_TOKEN --data-file=-

# Gemini API Key
echo -n "your_gemini_api_key" | \
  gcloud secrets create GEMINI_API_KEY --data-file=-
```

---

## Step 5: Grant IAM Permissions

```bash
# Get Cloud Build service account
export CB_SA="${PROJECT_ID}@cloudbuild.gserviceaccount.com"
export CR_SA="$(gcloud iam service-accounts list \
  --filter='displayName:Compute Engine default' \
  --format='value(email)')"

# Cloud Build: deploy to Cloud Run
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${CB_SA}" \
  --role="roles/iam.serviceAccountUser"

# Cloud Run: access GCS
gcloud storage buckets add-iam-policy-binding gs://${GCS_BUCKET} \
  --member="serviceAccount:${CR_SA}" \
  --role="roles/storage.objectAdmin"

# Cloud Run: read secrets
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
  --member="serviceAccount:${CR_SA}" \
  --role="roles/secretmanager.secretAccessor"
```

---

## Step 6: Deploy via Cloud Build

```bash
gcloud builds submit \
  --config=cloudbuild.yaml \
  --substitutions=_GCS_BUCKET=${GCS_BUCKET}
```

Or set up a Cloud Build trigger on push to main branch:

```bash
gcloud builds triggers create github \
  --repo-name=linebot-multimodal-rag \
  --repo-owner=YOUR_GITHUB_ACCOUNT \
  --branch-pattern='^main$' \
  --build-config=cloudbuild.yaml \
  --substitutions=_GCS_BUCKET=${GCS_BUCKET}
```

---

## Step 7: Get Webhook URL

```bash
gcloud run services describe linebot-multimodal-rag \
  --region=asia-east1 \
  --format='value(status.url)'
```

Webhook URL = `{SERVICE_URL}/webhook`

Register this URL in LINE Developers Console:
- Messaging API > Webhook URL
- Enable "Use webhook"

---

## Environment Variables Summary

| Variable | Source | Description |
|----------|--------|-------------|
| `LINE_CHANNEL_SECRET` | Secret Manager | For webhook signature verification |
| `LINE_CHANNEL_ACCESS_TOKEN` | Secret Manager | For sending messages |
| `GEMINI_API_KEY` | Secret Manager | For Gemini API access |
| `GCS_BUCKET` | Cloud Build substitution | GCS bucket name |
| `GEMINI_MODEL` | Cloud Build substitution | Default: `gemini-3-flash-preview` |

---

## Useful Commands

```bash
# View logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=linebot-multimodal-rag" \
  --limit=50 --format=json | jq '.[].textPayload'

# Check health
curl $(gcloud run services describe linebot-multimodal-rag \
  --region=asia-east1 --format='value(status.url)')/health

# Update a secret
echo -n "new_value" | gcloud secrets versions add LINE_CHANNEL_ACCESS_TOKEN --data-file=-
```
