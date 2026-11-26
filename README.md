# RollWatch — Deployment-Aware Health, Drift & Auto-Rollback Monitor

RollWatch is a production-ready DevOps & SRE monitoring tool for both **external public endpoints** and **managed services**. It performs real outbound DNS, TLS, and HTTP streaming probes, tracks rolling p95 latency and header/version drift, verifies post-deploy SLO windows triggered by CI/CD, and executes automated rollbacks via AWS SSM, GitHub Actions `workflow_dispatch`, or HMAC-signed webhooks.

## Architecture

- **Backend (`/backend`):** Python 3.12+, FastAPI, Uvicorn, Pydantic v2, `httpx`, `aiosqlite` (auto-migrated SQLite + 24h retention pruning), `boto3` (AWS SSM), `prometheus-client`.
- **Frontend (`/frontend`):** Next.js (App Router), TypeScript, Tailwind CSS, Recharts, Lucide icons.
- **DevOps:** Multi-stage non-root Dockerfiles, `docker-compose.yml`, GitHub Actions CI with `pytest` + Docker builds + Trivy `CRITICAL` CVE scan, and [docs/INTEGRATION.md](docs/INTEGRATION.md).

## Quick Start (Docker Compose)

```bash
cp .env.example .env
docker compose up --build
```

- Dashboard: `http://localhost:3000`
- Backend API & Swagger: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`
- Prometheus Metrics: `http://localhost:8000/metrics`

## Local Development

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate  |  Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Run tests:

```bash
cd backend
pytest -v
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Integration

See [docs/INTEGRATION.md](docs/INTEGRATION.md) for:
- Drop-in Go `/health` handler with `-ldflags` `gitSHA` injection
- GitHub Actions `POST /api/webhooks/deploy` step
- Minimal least-privilege IAM policy for `ssm:SendCommand` + `ssm:GetCommandInvocation`
