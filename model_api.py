"""The model APIs: one call per account, sending what the model reads (the "state") and our questions.

  ask(state, model="decision1")  -> (answers, input_tokens, seconds), retried on rate limits and server errors

Both models take the same request body; only the endpoint and how the key is sent differ. Keys are environment
variables (DECISION1_API_KEY, JEV_API_KEY), and so is Decision-1's endpoint (DECISION1_URL, Beacon's private Azure
address), all loaded from the .env file next to this one (private: never share or commit it). A variable already set
in the environment wins over .env, so a server can supply its own. Parallel calls are paced to stay under each
endpoint's tokens-per-minute quota.
"""
import os
import random
import threading
import time
from collections import deque
from pathlib import Path

import requests
from dotenv import load_dotenv

from questions import QUESTIONS

# --- What the model reads ----------------------------------------------------------------------------------------
TOKEN_BUDGET = 24_000      # most tokens one call may use (75% of the model's ~32k)


RESERVED_TOKENS = 7_200    # the questions and company details


TOKENS_PER_WORD = 1.5      # website text (measured 1.24 on average, up to 1.45)


TOKENS_PER_PAGE = 90       # each page's path, title and JSON

load_dotenv(Path(__file__).parent / ".env")  # pip install python-dotenv

MODELS = {
    "decision1": {"name": "Decision-1", "url": os.getenv("DECISION1_URL", ""), "model": "Decision-Model",
                  "key_env": "DECISION1_API_KEY", "auth": "api-key", "tokens_per_minute": 1_000_000},
    "jev": {"name": "Jev", "url": "https://opencode.ai/zen/v1/systemone", "model": "jev-1.13-free",
            "key_env": "JEV_API_KEY", "auth": "bearer", "tokens_per_minute": 200_000},
}
RETRIES = 6
RETRYABLE = {429, 500, 502, 503, 504, 529}


def api_key(model="decision1"):
    """The model's key from its environment variable; a clear message if it (or the endpoint) isn't set."""
    if not MODELS[model]["url"]:
        raise RuntimeError(f"No endpoint for {MODELS[model]['name']}: add the line  DECISION1_URL=<the address>  to "
                           "the .env file in the project folder.")
    env = MODELS[model]["key_env"]
    key = os.getenv(env, "").strip()
    if not key:
        raise RuntimeError(f"{env} is not set: add the line  {env}=<the key>  to the .env file in the project folder.")
    return key


def headers(model):
    key = api_key(model)
    return {"api-key": key} if MODELS[model]["auth"] == "api-key" else {"Authorization": f"Bearer {key}"}


class TokenPacer:
    """Keeps calls under the endpoint's tokens-per-minute quota, so the server doesn't start refusing them.

    It remembers when each call started in the last 60 seconds, and counts each as 16,000 tokens (a full call is at
    most 24,000; most use 8,000-16,000). A new call may start only if one more still fits under the quota:
      Decision-1's quota is 1,000,000 a minute: 1,000,000 / 16,000 = 62 calls in any 60 seconds
    When it doesn't fit, the call waits until the oldest call is more than 60 seconds old. The quota follows the
    server's own figure (the x-ratelimit-limit-tokens header on each answer), so a quota change needs no code change.
    Several calls run at once (in threads), so the record is guarded by a lock: one thread updates it at a time."""

    def __init__(self, tokens_per_minute, tokens_per_call=16_000):
        self.limit, self.per_call = tokens_per_minute, tokens_per_call
        self.started, self.lock = deque(), threading.Lock()  # start times of the calls in the last 60 seconds

    def wait(self):
        """Return once this call may start."""
        while True:
            with self.lock:
                now = time.monotonic()
                while self.started and now - self.started[0] > 60:  # forget calls older than a minute
                    self.started.popleft()
                if (len(self.started) + 1) * self.per_call <= self.limit or not self.started:
                    self.started.append(now)
                    return
                pause = 60 - (now - self.started[0]) + 0.05  # until the oldest call is a minute old
            time.sleep(pause)


PACERS = {name: TokenPacer(m["tokens_per_minute"]) for name, m in MODELS.items()}


def retry_wait(resp, attempt):
    """How many seconds to wait before trying a failed call again. If the server says how long (its Retry-After or
    rate-limit-reset headers), that; otherwise 2 seconds after the first failure, 4 after the second, 8, 16, ...
    Plus up to a second at random, so calls that failed together don't all retry at the same moment."""
    asked = 0.0
    for header in ("retry-after", "x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
        try:
            asked = max(asked, float((resp.headers if resp is not None else {}).get(header) or 0))
        except ValueError:
            pass
    return (asked or 2 ** attempt) + random.uniform(0, 1)


def ask(state, model="decision1"):
    """One call. Returns (answers, input_tokens, seconds); raises after RETRIES failed attempts."""
    cfg, pacer, auth = MODELS[model], PACERS[model], headers(model)
    for attempt in range(1, RETRIES + 1):
        pacer.wait()
        start = time.perf_counter()
        try:
            resp = requests.post(cfg["url"], headers=auth, timeout=90,
                                 json={"model": cfg["model"], "state": state, "questions": QUESTIONS})
        except (requests.ConnectionError, requests.Timeout):
            if attempt == RETRIES:
                raise
            time.sleep(retry_wait(None, attempt))
            continue
        if "x-ratelimit-limit-tokens" in resp.headers:
            pacer.limit = int(int(resp.headers["x-ratelimit-limit-tokens"]) * 0.95)
        if resp.status_code in RETRYABLE and attempt < RETRIES:
            time.sleep(retry_wait(resp, attempt))
            continue
        resp.raise_for_status()
        body = resp.json()
        return body["answers"], body.get("usage", {}).get("input_tokens"), time.perf_counter() - start
