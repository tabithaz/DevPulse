from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(
    title="DevPulse API",
    description="API for developer activity and repository analytics.",
    version="0.2.0",
)


class RepositoryActivity(BaseModel):
    name: str = Field(min_length=1)
    commits: int = Field(default=0, ge=0)
    pull_requests: int = Field(default=0, ge=0)
    issues: int = Field(default=0, ge=0)


class ActivitySummaryRequest(BaseModel):
    repositories: list[RepositoryActivity]


class ActivitySummary(BaseModel):
    repositories_tracked: int
    active_repositories: int
    total_commits: int
    total_pull_requests: int
    total_issues: int


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "DevPulse API is running"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/activity/summary", response_model=ActivitySummary)
def summarize_activity(payload: ActivitySummaryRequest) -> ActivitySummary:
    active_repositories = sum(
        1
        for repository in payload.repositories
        if repository.commits or repository.pull_requests or repository.issues
    )

    return ActivitySummary(
        repositories_tracked=len(payload.repositories),
        active_repositories=active_repositories,
        total_commits=sum(repository.commits for repository in payload.repositories),
        total_pull_requests=sum(
            repository.pull_requests for repository in payload.repositories
        ),
        total_issues=sum(repository.issues for repository in payload.repositories),
    )
