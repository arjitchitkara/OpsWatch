import asyncio

from fastapi import FastAPI, Query, Response, status

app = FastAPI(title="OpsWatch Failure Lab")
state = {"healthy": True}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "failure-lab"}


@app.head("/health")
def head_health() -> Response:
    return Response(status_code=status.HTTP_200_OK)


@app.get("/fail")
def fail() -> Response:
    return Response("intentional failure", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@app.get("/wrong-body")
def wrong_body() -> dict[str, str]:
    return {"message": "this body does not contain the expected text"}


@app.get("/slow")
async def slow(seconds: int = Query(default=8, ge=1, le=60)) -> dict[str, int | str]:
    await asyncio.sleep(seconds)
    return {"status": "slow", "seconds": seconds}


@app.post("/toggle")
def toggle() -> dict[str, bool]:
    state["healthy"] = not state["healthy"]
    return {"healthy": state["healthy"]}


@app.get("/toggle")
def toggle_status() -> Response:
    if state["healthy"]:
        return Response("toggle endpoint healthy", status_code=status.HTTP_200_OK)
    return Response("toggle endpoint failing", status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
