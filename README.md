# Gary

A phone-based voice assistant for older adults. See `AGENTS.md` for the architecture, ownership, safety invariants, and conventions.

## Quick start

Backend (from `backend/`):

```bash
uv sync
uv run uvicorn main:app --reload --port 8000
uv run pytest
```

Web (from `web/`):

```bash
npm install
npm run dev
```
