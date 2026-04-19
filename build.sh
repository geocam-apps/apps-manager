#!/bin/bash
set -e
cd "$(dirname "$0")"

echo "=== Installing Python deps ==="
pip3 install -r requirements.txt

echo "=== Building frontend ==="
cd frontend
npm install
npm run build
cd ..

echo "=== Build complete ==="
echo "Run: bash start_webserver.sh"
