"""Compare RAG-only answers and MCP-assisted answers on a synthetic PDF.

Use an isolated Open WebUI test instance with an existing admin session. The script
uploads one synthetic PDF and creates two independent chats for each question.
"""

import argparse
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import httpx

CASES = (
    ("q1-value", "How much revenue is shown for Q1?", "25"),
    ("q2-value", "How much revenue is shown for Q2?", "50"),
    ("q3-value", "How much revenue is shown for Q3?", "75"),
    ("maximum", "Which quarter has the highest revenue?", "Q3"),
    ("minimum", "Which quarter has the lowest revenue?", "Q1"),
    ("total", "What is the total revenue across the three quarters?", "150"),
    ("mean", "What is the arithmetic mean of the three values?", "50"),
    ("range", "What is the difference between the highest and lowest values?", "50"),
    ("increase", "By how much did revenue increase from Q1 to Q2?", "25"),
    ("unit", "What is the currency unit on the vertical axis? Use the abbreviation.", "USD"),
    ("horizontal-axis", "What is the label of the horizontal axis?", "Quarter"),
    ("caption", "Which figure number identifies the chart? Return just the number.", "1"),
)


def response_json(response: httpx.Response):
    response.raise_for_status()
    return response.json()


def upload(client: httpx.Client, path: Path) -> dict:
    file = response_json(
        client.post(
            "/api/v1/files/",
            params={"process_in_background": "false"},
            files={"file": ("quarterly-revenue.pdf", path.read_bytes(), "application/pdf")},
        )
    )
    for _ in range(60):
        status = response_json(client.get(f"/api/v1/files/{file['id']}/process/status"))
        if status["status"] == "completed":
            return file
        if status["status"] == "failed":
            raise RuntimeError("The synthetic PDF failed to index.")
        time.sleep(0.5)
    raise TimeoutError("The synthetic PDF is still processing.")


def ask(client: httpx.Client, model: str, file: dict, question: str, use_mcp: bool) -> dict:
    user_id, message_id = str(uuid4()), str(uuid4())
    attachment = {
        "type": "file",
        "id": file["id"],
        "name": file["filename"],
        "status": "uploaded",
        "context": "full",
    }
    prompt = question + (
        '\nReturn a JSON object with "answer" (short answer or unknown) and "source". '
        "Use the attached PDF as the source and avoid guessing."
    )
    if use_mcp:
        prompt += (
            f" Call extract_chart for attachment UUID {file['id']} on page 1 before answering. "
            "Include the source URL and page returned by the tool."
        )
    payload = {
        "stream": True,
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "files": [attachment],
        "params": {"function_calling": "native"},
        "tool_ids": ["server:mcp:chart-extraction"] if use_mcp else [],
        "parent_id": None,
        "id": message_id,
        "user_message": {
            "id": user_id,
            "parentId": None,
            "childrenIds": [message_id],
            "role": "user",
            "content": prompt,
            "files": [attachment],
        },
    }
    start = time.monotonic()
    for attempt in range(2):
        response = client.post("/api/chat/completions", json=payload)
        if response.status_code not in (429, 500, 502, 503, 504) or attempt:
            response.raise_for_status()
            break
        time.sleep(2)
    # The API can complete inline for server-side tools without a browser socket.
    for _ in range(60):
        chats = response_json(client.get("/api/v1/chats/", params={"page": 1}))
        for chat in chats[:6]:
            saved = response_json(client.get(f"/api/v1/chats/{chat['id']}"))
            candidate = saved["chat"]["history"]["messages"].get(message_id)
            if candidate and candidate.get("done"):
                output = candidate.get("output") or []
                tools = [
                    item.get("name", "") for item in output if item.get("type") == "function_call"
                ]
                text = candidate.get("content") or ""
                files = candidate.get("sources") or []
                return {
                    "output": text[:1200],
                    "tools": tools,
                    "cited": bool(files or f"/api/v1/files/{file['id']}/content" in text),
                    "latency_ms": round((time.monotonic() - start) * 1000),
                }
            if candidate:
                break
        time.sleep(0.5)
    raise TimeoutError("Open WebUI did not complete the chat.")


def check(response: str, expected: str) -> bool:
    try:
        match = re.search(r"\{[\s\S]*?\}", response)
        value = str(json.loads(match[0])["answer"]).strip() if match else response.strip()
    except (ValueError, KeyError, TypeError):
        value = response.strip()
    value = re.sub(r"\[\d+\]|https?://\S+", "", value).replace("$", "").strip().rstrip(".")
    if re.search(r"\b(?:unknown|unavailable|cannot|could not)\b", value, re.I):
        return False
    if expected.isdecimal():
        # Exclude quarter IDs and citations from numeric comparisons.
        numbers = re.findall(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?", value)
        return {float(number) for number in numbers} == {int(expected)}
    if re.fullmatch(r"Q[1-4]", expected, re.I):
        return set(re.findall(r"\bQ[1-4]\b", value.upper())) == {expected.upper()}
    return bool(re.search(r"\b" + re.escape(expected) + r"\b", value, re.I))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:3002")
    parser.add_argument("--model", default="glm-4-flash")
    parser.add_argument("--limit", type=int, choices=range(1, len(CASES) + 1), default=len(CASES))
    parser.add_argument("--parallel", type=int, choices=range(1, 4), default=1)
    args = parser.parse_args()
    token = os.environ["OPENWEBUI_TEST_TOKEN"]
    with httpx.Client(
        base_url=args.url,
        headers={"Authorization": f"Bearer {token}"},
        timeout=95,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        file = upload(client, args.pdf)

        def run_case(task):
            (case, question, expected), mode = task
            try:
                result = ask(client, args.model, file, question, mode == "mcp")
                result["correct"] = check(result["output"], expected)
            except (httpx.HTTPError, TimeoutError, KeyError) as error:
                code = (
                    error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
                )
                result = {"error": type(error).__name__, "http_status": code, "correct": False}
            return {"case": case, "mode": mode, "expected": expected, **result}

        tasks = [(case, mode) for case in CASES[: args.limit] for mode in ("rag", "mcp")]
        with ThreadPoolExecutor(max_workers=args.parallel) as pool:
            for result in pool.map(run_case, tasks):
                print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
