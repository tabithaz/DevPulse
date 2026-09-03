from fastapi import FastAPI

app = FastAPI(
    title="DevPulse API",
    description="API for developer activity and repository analytics.",
    version="0.1.0",
)


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "DevPulse API is running"}


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}
