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
- Browser dashboard for portfolio totals, growth rankings, alerts, snapshot freshness, GitHub quota, deltas, and collection
- Prometheus metrics for portfolio totals and per-repository snapshot freshness SLAs
- Prometheus RED metrics for API request rate, errors, latency, and in-flight work
- Validated request-ID propagation with structured completion logs for incident tracing
- Centralized browser security headers with a strict dashboard content policy
- ETag revalidation for efficient portfolio-dashboard polling
- Configurable per-repository snapshot retention with transactional pruning
- Stable cursor pagination for long repository snapshot histories
- Portfolio-wide snapshot deltas for measuring repository growth in one request
- Repository trend velocity and volatility across bounded snapshot windows
- Portfolio-wide growth rankings and aggregate repository velocity
- Portfolio freshness monitoring against configurable collection SLAs
- CI-ready portfolio release gates for freshness and alert budgets
- Cached portfolio alerts for high-impact repository changes
- Spreadsheet-safe portfolio reports combining state, deltas, and growth velocity
- Atomic batch collection for up to 25 repositories per request
- Durable idempotency keys for retry-safe snapshot collection
- Signed GitHub webhooks for automatic, retry-safe snapshot collection
- Durable, bounded audit history for API, batch, and webhook collection runs
- Atomic, integrity-checked SQLite backups with machine-readable manifests
- Guarded disaster recovery with schema validation and atomic database restores
- Concurrent SQLite access using WAL mode and configurable lock retries
- Integrity-checked SQLite WAL maintenance with optional offline compaction
- Optional constant-time API-key protection for manual snapshot collection

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
fastest-growing repositories and highest-priority portfolio alerts. A freshness
panel highlights repositories overdue for the 24-hour collection SLA and shows
snapshot ages. Use Refresh portfolio to recheck the panels without collecting
new data. A live GitHub quota badge reports collection capacity and the reset
time before a batch is started. It also
shows the change in stars, forks, and open issues between the selected
repository's two latest collections.

Set `DEVPULSE_API_KEY` to protect the manual single-repository and batch
collection endpoints. Clients then send the secret in `X-API-Key`. Comparison
uses constant-time verification, rejected requests cannot call GitHub or mutate
snapshot history, and signed webhooks plus read-only analytics remain available.
The dashboard can send the optional key for collection without storing it.

The `/metrics` endpoint also exposes bounded HTTP RED metrics labeled by FastAPI
route templates rather than raw repository URLs. This makes request volume,
error rates, latency distributions, and in-flight work available for alerts and
dashboards without creating unbounded labels from owner or repository names.
Every response also includes an `X-Request-ID`. DevPulse preserves a caller's
ID when it uses a bounded safe format, otherwise it generates one, and emits a
compact JSON completion log with the ID, route template, status, and duration.
This lets operators correlate a failed client call without logging raw dynamic
repository URLs.

Every response includes browser hardening headers that prevent MIME sniffing,
framing, referrer leakage, and access to unused device capabilities. The
dashboard also receives a restrictive Content Security Policy limited to its
same-origin API calls and bundled inline assets. HTTPS requests enable one-year
HTTP Strict Transport Security, while local HTTP development remains usable.

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
to use a different location, including a mounted Docker volume. DevPulse keeps
the newest 365 snapshots per repository by default so storage remains bounded.
Set `DEVPULSE_SNAPSHOT_RETENTION` to a different positive limit when needed.
SQLite runs in write-ahead logging mode so dashboard reads can continue during
snapshot writes. Brief write contention waits up to five seconds instead of
failing immediately; set `DEVPULSE_DB_BUSY_TIMEOUT_MS` to another positive
millisecond value when deployment traffic requires a different retry window.

Confirm the application and its snapshot database are ready with:

```bash
curl http://127.0.0.1:8000/ready
```

Create a consistent online backup without stopping the API:

```bash
mkdir -p backups
cd backend
python -m app.backup --output ../backups/devpulse.db
```

The command uses SQLite's online backup API, verifies the completed copy with
`PRAGMA integrity_check`, and atomically moves it into place only after
validation succeeds. Its JSON result includes the SHA-256 checksum, file size,
snapshot count, repository count, and collection-run count for automation and
restore audits. Existing files are preserved unless `--overwrite` is supplied.

Restore a verified backup while the API is stopped:

```bash
cd backend
python -m app.restore --backup ../backups/devpulse.db \
  --database ../data/devpulse.db --overwrite
```

The restore command opens the backup read-only, runs an integrity check,
validates every required table and column, and verifies the copied checksum and
row-count manifest before atomically replacing the destination. Without
`--overwrite`, an existing database is never changed.

Checkpoint accumulated WAL data, run SQLite's optimizer, and verify database
integrity with a machine-readable maintenance result:

```bash
cd backend
python -m app.maintenance --database ../data/devpulse.db
```

Add `--vacuum` during a maintenance window with the API stopped to compact the
database file. The result reports WAL frames, file sizes before and after,
integrity status, and stored row counts for operational auditing.

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
| `GET` | `/ready` | Readiness check with SQLite connectivity verification |
| `GET` | `/dashboard` | Interactive repository snapshot dashboard |
| `GET` | `/metrics?max_age_hours=24` | Export Prometheus portfolio and freshness metrics |
| `GET` | `/github/rate-limit` | Inspect live GitHub collection capacity and reset time |
| `GET` | `/github/{owner}/{repository}/snapshot` | Collect normalized GitHub repository metadata |
| `POST` | `/github/webhooks` | Verify GitHub events and collect repository snapshots automatically |
| `POST` | `/github/{owner}/{repository}/snapshots` | Collect and persist a repository snapshot |
| `POST` | `/github/snapshots/collect` | Collect and atomically persist up to 25 repository snapshots |
| `GET` | `/github/snapshots/collections?limit=50` | Audit recent successful collection runs and their triggers |
| `GET` | `/github/{owner}/{repository}/snapshots?limit=30` | Read recent snapshot history |
| `GET` | `/github/{owner}/{repository}/snapshots/page?limit=50` | Traverse history with stable keyset pagination |
| `GET` | `/github/{owner}/{repository}/snapshots/export?limit=365` | Download stored history as CSV |
| `GET` | `/github/{owner}/{repository}/snapshots/delta` | Compare the two latest stored snapshots |
| `GET` | `/github/{owner}/{repository}/snapshots/trend?limit=30` | Measure historical growth velocity and volatility |
| `GET` | `/github/snapshots/summary` | Summarize the latest state of every tracked repository |
| `GET` | `/github/snapshots/delta` | Aggregate changes across each repository's latest two snapshots |
| `GET` | `/github/snapshots/freshness?max_age_hours=24` | Find repositories with stale collection data |
| `GET` | `/github/snapshots/trends?limit=30` | Rank portfolio growth across stored snapshot windows |
| `GET` | `/github/snapshots/alerts` | Identify actionable changes across tracked repositories |
| `GET` | `/github/snapshots/gate` | Evaluate portfolio freshness and alert budgets for deployment safety |
| `GET` | `/github/snapshots/report.csv?trend_limit=30` | Export portfolio state, deltas, and growth velocity as CSV |
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

For longer histories, use the `/snapshots/page` endpoint. It returns up to 100
records plus `has_more` and an opaque `next_cursor`. Pass that cursor unchanged
to the next request. Cursors are bound to one repository, and newly collected
snapshots do not shift or duplicate records in an in-progress traversal.

Collect several repositories in one bounded request with
`POST /github/snapshots/collect`. DevPulse fetches every repository before
opening the storage transaction, then saves and prunes the complete batch
atomically. An upstream failure leaves snapshot history unchanged.

```json
{"repositories":[{"owner":"tabithaz","repository":"DevPulse"},{"owner":"tabithaz","repository":"TelemetryGuard"}]}
```

Both collection endpoints accept an `Idempotency-Key` header. Repeating the
same request with the same key returns the original `201` response with
`Idempotency-Replayed: true` without calling GitHub or writing another
snapshot. Reusing a key for a different repository request returns HTTP 409.
The newest 1,000 completed keys are retained in SQLite so retry safety survives
service restarts while storage remains bounded.

For event-driven collection, set `GITHUB_WEBHOOK_SECRET` and configure a GitHub
repository webhook to send `push` and `repository` events to
`POST /github/webhooks`. DevPulse verifies the `X-Hub-Signature-256` HMAC before
processing the payload, then uses `X-GitHub-Delivery` as a durable idempotency
key. Retried deliveries return the original response without another GitHub API
call or database write. Unsupported authenticated events are acknowledged and
ignored.

After collecting at least two snapshots, call
`GET /github/tabithaz/DevPulse/snapshots/delta` to see changes in stars,
forks, open issues, archived state, and default branch. The endpoint reads
stored history without making another GitHub API request. It returns
`no_data` or `insufficient_data` until a comparison is possible.

Use `GET /github/tabithaz/DevPulse/snapshots/trend?limit=30` to analyze a
longer stored window. The response reports net star, fork, and open-issue
changes, normalized per-day rates, and the population volatility of changes
between collections. Results include a stable ETag for efficient polling and
do not consume GitHub API quota.

Download up to 365 stored snapshots for a repository with
`GET /github/tabithaz/DevPulse/snapshots/export`. Rows are ordered from newest
to oldest and include counts, language, archived state, and default branch.
The CSV can be opened in a spreadsheet or used for external charts.

Use `GET /github/snapshots/summary` for a portfolio-wide view. It selects
only the newest stored snapshot per repository and reports active and archived
counts, aggregate stars, forks, open issues, language coverage, and the current
repository records without making live GitHub requests. The response includes a
stable `ETag` and honors `If-None-Match` with HTTP 304 when the portfolio has not
changed, reducing response work for dashboards and polling clients.

Use `GET /github/snapshots/delta` to compare each tracked repository's two
newest snapshots in one database query. The response aggregates changes in
stars, forks, and open issues, counts repositories gaining or losing stars,
and identifies repositories that need another collection before comparison.
It also supports ETag revalidation for efficient portfolio polling.

Use `GET /github/snapshots/freshness?max_age_hours=24` to enforce a collection
freshness SLA across the portfolio. The response separates fresh and stale
repositories, reports the newest and oldest snapshot ages, ranks the stalest
repositories first, and identifies when the next currently fresh repository
will become stale. It reads only stored data and does not consume GitHub API quota.

Use `GET /github/snapshots/trends?limit=30` to compare longer-term growth
across the full tracked portfolio. Repositories are ranked by star velocity,
with aggregate net changes and per-day growth for stars, forks, and open issues.
Repositories without enough stored history remain visible as insufficient data,
and the response supports ETag revalidation without consuming GitHub API quota.

Use `GET /github/snapshots/alerts` as an actionable monitoring feed. It detects
repository archival and reactivation, default-branch changes, star loss, and
configurable open-issue spikes from the latest stored snapshots. Alerts are
sorted by severity, repositories without enough history remain visible, and
ETag revalidation keeps polling efficient without using GitHub API quota.

The release gate returns its decision in `X-DevPulse-Gate`. Add
`enforce_http=true` to receive HTTP 503 when the policy fails, allowing standard
CI tools to block a deployment without custom JSON parsing:

```bash
curl --fail "http://127.0.0.1:8000/github/snapshots/gate?enforce_http=true"
```

Download `GET /github/snapshots/report.csv` for a spreadsheet-ready portfolio
report. Each repository includes its current counts, latest changes, and
normalized daily growth rates in one row. Text fields are escaped to prevent
spreadsheet formula execution, and repositories with only one snapshot remain
visible with an `insufficient_data` status.

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
