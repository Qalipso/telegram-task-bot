#!/bin/bash
# Push all application images to Docker Hub / registry
# Usage: ./push.sh [REGISTRY] [VERSION]
# Example: ./push.sh myregistry.azurecr.io 1.0.0

set -e

REGISTRY="${1:-docker.io}"
VERSION="${2:-latest}"
IMAGES=("aiwip-api:$VERSION" "aiwip-worker:$VERSION" "aiwip-web:$VERSION")

echo "Pushing to registry: $REGISTRY"

for image in "${IMAGES[@]}"; do
  # Tag image
  docker tag "$image" "$REGISTRY/$image"
  
  # Push
  echo "Pushing $REGISTRY/$image..."
  docker push "$REGISTRY/$image"
done

echo "All images pushed successfully!"
