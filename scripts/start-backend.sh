#!/bin/bash
# Start backend API server
cd "$(dirname "$0")/../backend"
echo "Starting backend on http://localhost:8000"
echo "API docs: http://localhost:8000/docs"
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
