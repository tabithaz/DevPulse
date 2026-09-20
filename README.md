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

## Stack

- Python 3.12
- FastAPI and Pydantic
- pytest and HTTPX
- GitHub Actions

## Run locally

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend
uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`. FastAPI's interactive documentation is available at `http://127.0.0.1:8000/docs`.

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
| `POST` | `/activity/summary` | Aggregate repository activity |
| `POST` | `/activity/rankings?limit=10` | Rank repositories by total activity |
| `POST` | `/delivery/lead-time` | Classify delivery lead-time health |

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
│   │   └── *.py                 # focused engineering metric modules
│   ├── tests/                   # API and analytics regression tests
│   └── requirements.txt
└── .github/workflows/test.yml   # Python 3.12 test workflow
```

## Next milestones

- Continue connecting metric modules through the API surface
- Add GitHub ingestion with token and rate-limit handling
- Persist repository snapshots for historical comparisons
- Build a dashboard for exploring trends over time
