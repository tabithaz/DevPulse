# DevPulse

DevPulse is a FastAPI service for turning repository activity into clear engineering-delivery metrics. It validates repository-level commit, pull request, and issue counts, then returns summaries and rankings that make activity distribution easy to inspect.

The project also includes a tested analytics library for delivery cadence, lead time, review flow, deployment health, contributor workload, and repository trends.

## Current capabilities

- Repository activity summaries and ranked activity results
- Strict request validation for negative counts, blank names, and duplicate repositories
- Activity coverage, averages, median, range, and event-share calculations
- Dominant activity, diversity, and repository-concentration indicators
- Delivery and deployment metrics such as frequency, batch size, rollback rate, and change-failure rate
- Pull request metrics such as lead time, review latency, review cycles, queue tail, size, throughput, and rework
- Contributor metrics including ownership concentration, workload, reviewer load, and contribution streaks
- Trend, volatility, forecasting, inactivity-gap, branch-staleness, and release-stability analysis
- Automated pytest coverage and GitHub Actions validation
- Browser dashboard for portfolio totals, snapshot deltas, collection, and repository trends

## Stack

- Python 3.12
- FastAPI and Pydantic
- pytest and HTTPX
- Docker
- GitHub Actions
- SQLite snapshot history

## Run locally

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload
```

The dashboard is available at `http://127.0.0.1:8000/dashboard`. The API is available at `http://127.0.0.1:8000`, and FastAPI's interactive documentation is available at `http://127.0.0.1:8000/docs`.
The dashboard loads portfolio-wide totals from stored snapshots and shows the
change in stars, forks, and open issues between the selected repository's two
latest collections.

## Run with Docker

```bash
docker build -t devpulse-api .
docker run --rm -p 8000:8000 devpulse-api
```

For higher GitHub API limits or private repositories, set a token before starting the service:

```bash
export GITHUB_TOKEN=github_pat_your_token
```

The token is only sent to GitHub and is never included in API responses.
Snapshot history is stored in `devpulse.db` by default. Set `DEVPULSE_DB_PATH`
to use a different location, including a mounted Docker volume.

Confirm the container is ready with:

```bash
curl http://127.0.0.1:8000/health
```

## Example request

```bash
curl -X POST http://127.0.0.1:8000/activity/summary \
  -H "Content-Type: application/json" \
  -d '{
    "repositories": [
      {"name": "api", "commits": 18, "pull_requests": 6, "issues": 3},
      {"name": "dashboard", "commits": 12, "pull_requests": 4, "issues": 5}
    ]
  }'
```

Example response:

```json
{
  "repositories_tracked": 2,
  "active_repositories": 2,
  "inactive_repositories": 0,
  "activity_coverage_percent": 100.0,
  "average_events_per_repository": 24.0,
  "average_events_per_active_repository": 24.0,
  "median_events_per_repository": 24.0,
  "repository_activity_range": 6,
  "total_commits": 30,
  "total_pull_requests": 10,
  "total_issues": 8,
  "total_events": 48,
  "commit_share_percent": 62.5,
  "pull_request_share_percent": 20.8,
  "issue_share_percent": 16.7,
  "dominant_activity_type": "commits",
  "dominant_activity_events": 30,
  "activity_diversity_score": 80.7,
  "activity_diversity": "diverse",
  "most_active_repository": "api",
  "most_active_repository_events": 27,
  "most_active_repository_share_percent": 56.2,
  "activity_concentration": "concentrated"
}
```

## API endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Basic API status |
| `GET` | `/health` | Health check |
| `GET` | `/dashboard` | Interactive repository snapshot dashboard |
| `GET` | `/github/{owner}/{repository}/snapshot` | Collect normalized GitHub repository metadata |
| `POST` | `/github/{owner}/{repository}/snapshots` | Collect and persist a repository snapshot |
| `GET` | `/github/{owner}/{repository}/snapshots?limit=30` | Read recent snapshot history |
| `GET` | `/github/{owner}/{repository}/snapshots/export?limit=365` | Download stored history as CSV |
| `GET` | `/github/{owner}/{repository}/snapshots/delta` | Compare the two latest stored snapshots |
| `GET` | `/github/snapshots/summary` | Summarize the latest state of every tracked repository |
| `POST` | `/activity/summary` | Aggregate repository activity |
| `POST` | `/activity/rankings?limit=10` | Rank repositories by total activity |
| `POST` | `/delivery/lead-time` | Classify delivery lead-time health |
| `POST` | `/deployments/health` | Combine deployment frequency, batch, rollback, and failure health |

Collect a live repository snapshot with:

```bash
curl http://127.0.0.1:8000/github/tabithaz/DevPulse/snapshot
```

The endpoint returns normalized repository metadata and maps missing repositories, exhausted GitHub rate limits, and upstream failures to clear HTTP errors.

Persist the current snapshot and retrieve its history with:

```bash
curl -X POST http://127.0.0.1:8000/github/tabithaz/DevPulse/snapshots
curl "http://127.0.0.1:8000/github/tabithaz/DevPulse/snapshots?limit=10"
```

After collecting at least two snapshots, call
`GET /github/tabithaz/DevPulse/snapshots/delta` to see changes in stars,
forks, open issues, archived state, and default branch. The endpoint reads
stored history without making another GitHub API request. It returns
`no_data` or `insufficient_data` until a comparison is possible.

Download up to 365 stored snapshots for a repository with
`GET /github/tabithaz/DevPulse/snapshots/export`. Rows are ordered from newest
to oldest and include counts, language, archived state, and default branch.
The CSV can be opened in a spreadsheet or used for external charts.

Use `GET /github/snapshots/summary` for a portfolio-wide view. It selects
only the newest stored snapshot per repository and reports active and archived
counts, aggregate stars, forks, open issues, language coverage, and the current
repository records without making live GitHub requests.

The deployment-health endpoint accepts aligned deployment timestamps, change counts, and success outcomes:

```bash
curl -X POST http://127.0.0.1:8000/deployments/health \
  -H "Content-Type: application/json" \
  -d '{
    "deployment_days": [0, 1, 3, 4],
    "changes_per_deployment": [3, 5, 8, 10],
    "outcomes": [true, true, true, true]
  }'
```

## Run tests

```bash
cd backend
PYTHONPATH=. pytest -q
```

The test suite covers API behavior, request validation, empty and zero-activity inputs, deterministic ranking, and the individual analytics modules.

## Project structure

```text
.
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application and activity endpoints
│   │   ├── static/dashboard.html # runnable repository dashboard
│   │   └── *.py                 # focused engineering metric modules
│   ├── tests/                   # API and analytics regression tests
│   └── requirements.txt
├── Dockerfile                   # non-root API container
└── .github/workflows/test.yml   # tests and container health check
```

## v1.0 scope

DevPulse v1.0 includes a documented analytics API, live GitHub ingestion, durable snapshot history, an interactive dashboard, automated tests, and a containerized runnable demo.
