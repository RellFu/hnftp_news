# Hainan Pitch Assistant - One-command setup and run

.PHONY: install install-backend install-frontend install-scripts \
	corpus chunk index eval start-backend start-frontend start help

help:
	@echo "Hainan Pitch Assistant"
	@echo ""
	@echo "Setup:"
	@echo "  make install          Install all dependencies"
	@echo "  make install-backend   Install backend Python deps"
	@echo "  make install-frontend Install frontend npm deps"
	@echo "  make install-scripts   Install script deps (corpus manager)"
	@echo ""
	@echo "Data & indices:"
	@echo "  make corpus           Run corpus_manager.py (fetch documents)"
	@echo "  make chunk            Chunk documents for retrieval"
	@echo "  make index            Build index manifest"
	@echo ""
	@echo "Run:"
	@echo "  make start             Start backend + frontend (requires two terminals or background)"
	@echo "  make start-backend     Start FastAPI backend only"
	@echo "  make start-frontend    Start Next.js frontend only"
	@echo ""
	@echo "Evaluation:"
	@echo "  make eval              Run evaluation harness"

install: install-backend install-frontend install-scripts

install-backend:
	cd backend && pip install -r requirements.txt

install-frontend:
	cd frontend && npm install

install-scripts:
	pip install requests beautifulsoup4 trafilatura PyPDF2 2>/dev/null || true

corpus:
	python scripts/corpus_manager.py

chunk:
	python knowledge_base/scripts/chunk.py

index:
	python knowledge_base/scripts/build_index.py

eval:
	python evaluation/harness/run.py

start-backend:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0

start-frontend:
	cd frontend && npm run dev

start:
	@echo "Run in two terminals:"
	@echo "  Terminal 1: make start-backend"
	@echo "  Terminal 2: make start-frontend"
	@echo "Then open http://localhost:3000"
