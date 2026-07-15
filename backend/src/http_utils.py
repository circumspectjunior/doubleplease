from __future__ import annotations

import time

import requests

REDACTED_PARAMS = {"apiKey"}


class ApiRequestError(RuntimeError):
    pass


def get_json(
    url: str,
    params: dict,
    headers: dict | None = None,
    timeout: int = 30,
    max_retries: int = 4,
    backoff_seconds: float = 8.0,
) -> dict | list:
    """GET with JSON response, retrying on 429, and never leaking secret query
    params (e.g. apiKey) into raised error messages."""
    safe_params = {k: ("<redacted>" if k in REDACTED_PARAMS else v) for k, v in params.items()}

    for attempt in range(max_retries):
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code == 429:
            time.sleep(backoff_seconds * (attempt + 1))
            continue
        if not resp.ok:
            raise ApiRequestError(f"{resp.status_code} calling {url} params={safe_params}")
        return resp.json()

    raise ApiRequestError(f"Rate limited after {max_retries} retries calling {url} params={safe_params}")
