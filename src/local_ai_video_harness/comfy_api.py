from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class ComfyApiError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, base_url: str, timeout_seconds: int = 3600, poll_seconds: float = 2):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = poll_seconds

    def request_json(self, path: str, payload=None, method: str = "GET"):
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(self.base_url + path, data=data, method=method, headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60) as response:
            raw = response.read()
        return json.loads(raw.decode("utf-8")) if raw else {}

    def wait_until_ready(self, seconds: int = 120):
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                self.request_json("/system_stats")
                return
            except Exception:
                time.sleep(1)
        raise TimeoutError(f"ComfyUI did not become ready: {self.base_url}")

    def submit(self, workflow: dict) -> str:
        result = self.request_json("/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())}, "POST")
        prompt_id = result.get("prompt_id")
        if not prompt_id:
            raise ComfyApiError(json.dumps(result, ensure_ascii=False))
        return prompt_id

    def wait_for_history(self, prompt_id: str) -> dict:
        deadline = time.time() + self.timeout_seconds
        while time.time() < deadline:
            history = self.request_json(f"/history/{prompt_id}")
            if prompt_id in history:
                item = history[prompt_id]
                if item.get("status", {}).get("status_str") == "error":
                    raise ComfyApiError(json.dumps(item, ensure_ascii=False, indent=2))
                return item
            time.sleep(self.poll_seconds)
        raise TimeoutError(f"ComfyUI prompt timed out: {prompt_id}")

    @staticmethod
    def output_items(history: dict):
        for node_output in history.get("outputs", {}).values():
            for key in ("videos", "gifs", "images", "audio"):
                yield from node_output.get(key, [])

    def download(self, item: dict, destination: Path):
        query = urlencode({key: item[key] for key in ("filename", "subfolder", "type") if key in item})
        with urlopen(self.base_url + "/view?" + query, timeout=120) as response:
            destination.write_bytes(response.read())

    def upload_image(self, path: Path) -> str:
        """Upload an image and return the server-side filename.

        Used for first-frame continuity chaining, where the last frame of a
        completed shot becomes the ``first_frame`` input of the next shot.
        """
        boundary = "----VideoHarness" + uuid.uuid4().hex
        body = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: image/png\r\n\r\n".encode(),
            path.read_bytes(),
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        request = Request(
            self.base_url + "/upload/image",
            data=b"".join(body),
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
        return result.get("name", path.name)


def clone_workflow(workflow: dict) -> dict:
    return copy.deepcopy(workflow)


def set_input(workflow: dict, node_id: str, input_name: str, value):
    node = workflow.get(str(node_id))
    if not node or "inputs" not in node:
        raise KeyError(f"Workflow node not found: {node_id}")
    if input_name not in node["inputs"]:
        raise KeyError(f"Workflow input not found: {node_id}.{input_name}")
    node["inputs"][input_name] = value
