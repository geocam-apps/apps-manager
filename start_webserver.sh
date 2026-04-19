#!/bin/bash
cd "$(dirname "$0")"
source .env 2>/dev/null || true
exec ~/.local/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8080 --workers 1
