#!/usr/bin/env bash
# import_qdrant.sh — Run on the SERVER to import a Qdrant backup.
# Usage: ./import_qdrant.sh /path/to/qdrant_backup.tar.gz
set -euo pipefail

TARBALL="${1:-}"

if [ -z "$TARBALL" ]; then
    echo "Usage: $0 <path-to-qdrant_backup.tar.gz>"
    exit 1
fi

if [ ! -f "$TARBALL" ]; then
    echo "ERROR: File not found: $TARBALL"
    exit 1
fi

# Use the same volume name as docker-compose.prod.yml
VOLUME="sin-chatbot_qdrant_data"

echo "==> Creating Docker volume: $VOLUME (if not exists)..."
docker volume create "$VOLUME" 2>/dev/null || true

echo "==> Stopping Qdrant container if running..."
docker stop sin_chatbot_qdrant 2>/dev/null || true

echo "==> Importing $TARBALL into volume $VOLUME ..."
docker run --rm \
    -v "${VOLUME}:/data" \
    -v "$(cd "$(dirname "$TARBALL")" && pwd):/backup:ro" \
    alpine \
    sh -c "rm -rf /data/* && tar xzf /backup/$(basename "$TARBALL") -C /data"

echo ""
echo "==> Done! Volume $VOLUME populated."
echo ""
echo "Next steps:"
echo "  1. Start Qdrant:  cd ~/sin-chatbot && docker compose -f docker-compose.prod.yml up -d"
echo "  2. Verify:        curl -s http://localhost:6333/collections/sin_docs | python3 -m json.tool"
