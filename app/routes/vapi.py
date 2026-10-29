"""Webhooks called by Vapi.

/vapi/tools   synchronous: the LLM is waiting for our answer mid-call.
/vapi/events  asynchronous: notifications such as the end-of-call report.

Both paths share one dispatcher keyed on message.type, so a server URL pointed
at either one still works. Tool responses are ALWAYS HTTP 200: Vapi ignores
other status codes and the caller would hear "no result returned".
"""
import hmac
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.services import calls as call_svc
from app.services.agent_tools import SYSTEM_ERROR, TOOLS, CallContext

log = logging.getLogger("app.vapi")
router = APIRouter(prefix="/vapi", tags=["vapi"])


def verify_vapi(
    authorization: str | None = Header(None),
    x_vapi_secret: str | None = Header(None),
) -> None:
    """Accept either Vapi auth style: a Bearer Token credential
    (Authorization: Bearer <secret>) or the legacy X-Vapi-Secret header."""
    secret = get_settings().vapi_webhook_secret
    if not secret:
        log.warning("VAPI_WEBHOOK_SECRET is not set; webhook auth is disabled")
        return
    supplied = x_vapi_secret or (authorization or "").removeprefix("Bearer ").strip()
    if not supplied or not hmac.compare_digest(supplied, secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


def _ctx(message: dict) -> CallContext:
    call = message.get("call") or {}
    customer = call.get("customer") or message.get("customer") or {}
    return CallContext(call_id=call.get("id"), caller_number=customer.get("number"))


def _parse_tool_call(item: dict) -> tuple[str | None, str | None, dict]:
    fn = item.get("function") or {}
    name = fn.get("name") or item.get("name")
    args = fn.get("arguments", item.get("arguments")) or {}
    if isinstance(args, str):  # defensive: some providers send a JSON string
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return item.get("id"), name, args


def _handle_tool_calls(message: dict, db: Session) -> dict:
    ctx = _ctx(message)
    results = []
    for item in message.get("toolCallList") or []:
        call_id, name, args = _parse_tool_call(item)
        handler = TOOLS.get(name)
        if handler is None:
            results.append({"toolCallId": call_id, "error": f"Unknown tool '{name}'."})
            continue
        try:
            out = handler(db, args, ctx)
        except Exception:  # never leave the caller in silence
            log.exception("Tool %s crashed call_id=%s", name, ctx.call_id)
            db.rollback()
            out = SYSTEM_ERROR
        log.info("tool=%s call_id=%s result=%s", name, ctx.call_id, out)
        results.append({"toolCallId": call_id, "result": json.dumps(out)})
    return {"results": results}


def _handle_end_of_call(message: dict, db: Session) -> dict:
    ctx = _ctx(message)
    if not ctx.call_id:
        return {}
    artifact = message.get("artifact") or {}
    analysis = message.get("analysis") or {}
    transcript = artifact.get("transcript") or message.get("transcript")
    summary = analysis.get("summary") or message.get("summary")
    ended = message.get("endedReason")
    call_svc.record_end_of_call(db, ctx.call_id, ctx.caller_number, ended, summary, transcript, message)
    log.info("end_of_call call_id=%s ended_reason=%s caller=%s", ctx.call_id, ended, ctx.caller_number)
    return {}


async def _dispatch(request: Request, db: Session) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    message = body.get("message") or {}
    kind = message.get("type")
    if kind == "tool-calls":
        return _handle_tool_calls(message, db)
    if kind == "end-of-call-report":
        try:
            return _handle_end_of_call(message, db)
        except Exception:
            log.exception("Failed to store end-of-call report")
            db.rollback()
            return {}
    log.debug("Ignoring Vapi message type=%s", kind)
    return {}


@router.post("/tools", dependencies=[Depends(verify_vapi)])
async def tools(request: Request, db: Session = Depends(get_db)):
    return await _dispatch(request, db)


@router.post("/events", dependencies=[Depends(verify_vapi)])
async def events(request: Request, db: Session = Depends(get_db)):
    return await _dispatch(request, db)
