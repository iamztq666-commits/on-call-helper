import json
from fastapi import APIRouter
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from agent.clarifier import maybe_clarify
from agent.runner import run_agent

router = APIRouter()


class ChatBody(BaseModel):
    message: str
    session_id: str = ""
    history: list = []


class EvalBody(BaseModel):
    strategy: str = "rrf+rewrite"
    cases: list[str] = []


@router.get("")
async def ui():
    return FileResponse("static/v3.html")


@router.post("/chat")
async def chat(body: ChatBody):
    clarify = await maybe_clarify(body.message, body.history)

    if clarify["type"] == "clarification":
        async def clarify_stream():
            yield f"data: {json.dumps(clarify, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        return StreamingResponse(clarify_stream(), media_type="text/event-stream")

    async def agent_stream():
        async for event in run_agent(body.message, body.history):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(agent_stream(), media_type="text/event-stream")


@router.post("/eval")
async def eval_harness(body: EvalBody):
    from harness.runner import HarnessRunner
    runner = HarnessRunner()
    report = await runner.run(
        strategies=[body.strategy],
        case_ids=body.cases if body.cases else None,
    )
    return report
