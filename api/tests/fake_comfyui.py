from collections import defaultdict
from uuid import uuid4

from fastapi import FastAPI, Request, Response

app = FastAPI()
history_requests: defaultdict[str, int] = defaultdict(int)


@app.get("/system_stats")
def system_stats() -> dict[str, object]:
    return {"system": {"status": "ok"}}


@app.post("/prompt")
def submit_prompt() -> dict[str, str]:
    return {"prompt_id": str(uuid4())}


@app.get("/history/{prompt_id}")
def prompt_history(prompt_id: str) -> dict[str, object]:
    history_requests[prompt_id] += 1
    if history_requests[prompt_id] == 1:
        return {
            prompt_id: {
                "status": {
                    "status_str": "running",
                    "messages": [["progress", {"value": 3, "max": 10}]],
                },
                "outputs": {},
            }
        }
    return {
        prompt_id: {
            "status": {"status_str": "success"},
            "outputs": {
                "output": {
                    "videos": [
                        {
                            "filename": "ugc-preview.mp4",
                            "subfolder": "",
                            "type": "output",
                        }
                    ]
                }
            },
        }
    }


@app.get("/view")
def view_output() -> Response:
    return Response(b"fake-mp4-output", media_type="video/mp4")


@app.post("/upload/image")
async def upload_input(request: Request) -> dict[str, str]:
    await request.body()
    return {"name": "uploaded-input"}
