"""Create or update the Vapi assistant from files in this repo.

    python scripts/sync_assistant.py --dry-run   # print the config, send nothing
    python scripts/sync_assistant.py             # create, or update if VAPI_ASSISTANT_ID is set

Keeping the assistant as code means the prompt and tool schemas are versioned
with the backend, and the server URL and webhook secret come from .env
instead of being pasted into the dashboard by hand.
"""
import json
import os
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
VAPI_API = "https://api.vapi.ai"


def build_config(base_url: str, secret: str) -> dict:
    prompt = (ROOT / "prompts" / "system_prompt.md").read_text()
    prompt = re.sub(r"<!--.*?-->\s*", "", prompt, flags=re.S).strip()  # strip engineer comments

    raw = (ROOT / "vapi" / "assistant.json").read_text()
    raw = raw.replace("__BASE_URL__", base_url.rstrip("/")).replace("__WEBHOOK_SECRET__", secret)
    config = json.loads(raw)
    config["model"]["messages"][0]["content"] = prompt
    return config


def main() -> None:
    load_dotenv(ROOT / ".env")
    dry_run = "--dry-run" in sys.argv

    base_url = os.getenv("PUBLIC_BASE_URL", "")
    secret = os.getenv("VAPI_WEBHOOK_SECRET", "")
    api_key = os.getenv("VAPI_API_KEY", "")
    assistant_id = os.getenv("VAPI_ASSISTANT_ID", "")

    missing = [n for n, val in [("PUBLIC_BASE_URL", base_url), ("VAPI_WEBHOOK_SECRET", secret)] if not val]
    if not dry_run and not api_key:
        missing.append("VAPI_API_KEY")
    if missing:
        sys.exit(f"Missing in .env: {', '.join(missing)}")
    if not base_url.startswith("https://"):
        sys.exit("PUBLIC_BASE_URL must be a public https URL (Railway or a tunnel), not localhost.")

    config = build_config(base_url, secret)

    if dry_run:
        printable = json.dumps(config, indent=2).replace(secret, "***")
        print(printable)
        return

    headers = {"Authorization": f"Bearer {api_key}"}
    if assistant_id:
        r = httpx.patch(f"{VAPI_API}/assistant/{assistant_id}", json=config, headers=headers, timeout=30)
    else:
        r = httpx.post(f"{VAPI_API}/assistant", json=config, headers=headers, timeout=30)

    if r.status_code >= 400:
        sys.exit(f"Vapi returned {r.status_code}:\n{r.text}")

    data = r.json()
    action = "Updated" if assistant_id else "Created"
    print(f"{action} assistant {data['id']} ({data.get('name')})")
    if not assistant_id:
        print(f"\nAdd this to .env so future runs update instead of creating a new one:\nVAPI_ASSISTANT_ID={data['id']}")


if __name__ == "__main__":
    main()