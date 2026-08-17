#!/usr/bin/env bash
# export_qdrant.sh — Run on your LOCAL machine to export the Qdrant volume.
# Produces qdrant_backup.tar.gz in the current directory.
set -euo pipefail

BACKUP_FILE="qdrant_backup.tar.gz"

echo "==> Looking for Qdrant Docker volume..."

# Try common volume name patterns
VOLUME=""
for candidate in \
    "sin_chatbot_qdrant_data" \
    "sinchatbot_qdrant_data" \
    "sin-chatbot_qdrant_data" \
    "qdrant_data"; do
    if docker volume inspect "$candidate" &>/dev/null; then
        VOLUME="$candidate"
        break
    fi
done

# If none of the common names matched, search for any volume containing "qdrant"
if [ -z "$VOLUME" ]; then
    VOLUME=$(docker volume ls --format '{{.Name}}' | grep -i qdrant | head -1 || true)
fi

if [ -z "$VOLUME" ]; then
    echo "ERROR: No Qdrant volume found."
    echo "Available volumes:"
    docker volume ls --format '  {{.Name}}'
    exit 1
fi

echo "==> Found volume: $VOLUME"
echo "==> Exporting to $BACKUP_FILE ..."

docker run --rm \
    -v "${VOLUME}:/data" \
    -v "$(pwd):/backup" \
    alpine \
    tar czf "/backup/${BACKUP_FILE}" -C /data .

SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
echo ""
echo "==> Done! Backup: $BACKUP_FILE ($SIZE)"
echo ""
echo "Next step — copy to the server:"
echo "  scp -i siemens_ed25519 $BACKUP_FILE siemens@35.87.248.186:~/"
