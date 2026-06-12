import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from scripts.config import get_settings
from scripts.db import push_event

logger = logging.getLogger(__name__)


def _handle_request(client: SocketModeClient, req: SocketModeRequest) -> None:
    client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

    if req.type != "events_api":
        return

    event = req.payload.get("event", {})
    if event.get("type") not in ("message",):
        return

    # Allow thread replies and thread broadcasts through; drop bot/system subtypes
    subtype = event.get("subtype")
    if subtype and subtype not in ("thread_broadcast",):
        return

    s = get_settings()
    allowed = [c.strip() for c in s.slack_channels.split(",") if c.strip()]
    if allowed and event.get("channel") not in allowed:
        return

    ts = event.get("ts", "")
    thread_ts = event.get("thread_ts")
    is_thread_reply = bool(thread_ts and thread_ts != ts)

    raw_json = json.dumps({
        "channel":         event.get("channel", ""),
        "user":            event.get("user", ""),
        "body":            event.get("text", ""),
        "ts":              ts,
        "thread_ts":       thread_ts,
        "is_thread_reply": is_thread_reply,
        "reply_count":     event.get("reply_count", 0),
    })

    event_type = "thread_reply" if is_thread_reply else "message"
    
    # For thread replies, find parent message and link via parent_event_id
    parent_event_id = None
    if is_thread_reply:
        # In production, you'd look up the parent message's event_id from DB
        # For now, we queue the thread_reply and let worker handle context
        pass
    
    eid = push_event("slack", event_type, raw_json, parent_event_id=parent_event_id)
    logger.info("Queued Slack %s from channel %s (event_id=%d, thread=%s)", 
                event_type, event.get("channel"), eid, thread_ts or "none")


def run_slack_connector() -> None:
    import threading
    s = get_settings()
    web_client = WebClient(token=s.slack_bot_token)
    socket_client = SocketModeClient(app_token=s.slack_app_token, web_client=web_client)
    socket_client.socket_mode_request_listeners.append(_handle_request)
    socket_client.connect()
    logger.info("Slack connector listening")
    threading.Event().wait()


if __name__ == "__main__":
    from scripts.db import init_db
    logging.basicConfig(level=logging.INFO)
    init_db()
    run_slack_connector()
