#!/bin/bash
set -e

PROJECT_ID="project-a0fcdf5b-f2be-45d8-87c"
REGION="asia-south1"
IMAGE="asia-south1-docker.pkg.dev/${PROJECT_ID}/incidentiq/api:latest"
SA_EMAIL="incidentiq-sa@${PROJECT_ID}.iam.gserviceaccount.com"

echo "Configuring docker auth..."
gcloud auth configure-docker ${REGION}-docker.pkg.dev --quiet

echo "Building Docker image..."
docker build -t ${IMAGE} .

echo "Pushing to Artifact Registry..."
docker push ${IMAGE}

echo "Deploying to Cloud Run..."
gcloud run deploy incidentiq \
  --image=${IMAGE} \
  --region=${REGION} \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=2Gi \
  --cpu=2 \
  --timeout=300 \
  --min-instances=1 \
  --service-account=${SA_EMAIL} \
  --set-env-vars="CLOUD_RUN=true" \
  --set-secrets="GROQ_API_KEY=GROQ_API_KEY:latest,GEMINI_API_KEY=GEMINI_API_KEY:latest,LANGCHAIN_API_KEY=LANGCHAIN_API_KEY:latest,LANGCHAIN_TRACING_V2=LANGCHAIN_TRACING_V2:latest,LANGCHAIN_PROJECT=LANGCHAIN_PROJECT:latest"

echo "Deployment complete!"
