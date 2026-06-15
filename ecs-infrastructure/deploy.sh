#!/bin/bash
set -e

echo "Deploying to AWS ECS..."

# Force a new deployment of the incidentiq service using the existing task definition
# This triggers ECS to pull the latest image tagged in ECR and perform a rolling update
aws ecs update-service \
  --cluster incidentiq-cluster \
  --service incidentiq-service \
  --force-new-deployment \
  --region ap-south-1

echo "Deployment initiated. ECS will perform a rolling update and health check the new task."
