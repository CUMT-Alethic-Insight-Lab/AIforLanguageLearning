"""Run a dependency-light HELIX browser smoke test through Chromium CDP.

The backend and a Chromium-family browser with remote debugging enabled must
already be running. Example::

    python scripts/qa_browser_smoke.py \
        --base-url http://127.0.0.1:8012 \
        --cdp-url http://127.0.0.1:9222

Admin credentials are read from HELIX_QA_ADMIN_USERNAME and
HELIX_QA_ADMIN_PASSWORD so they never appear in command history or reports.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from websockets.sync.client import connect


class BrowserSmokeError(RuntimeError):
    """Raised when the browser-visible contract is broken."""


class CdpClient:
    def __init__(self, websocket_url: str, timeout: float = 15.0) -> None:
        self.websocket = connect(websocket_url, max_size=16 * 1024 * 1024)
        self.timeout = timeout
        self.sequence = 0
        self.events: list[dict[str, Any]] = []

    def close(self) -> None:
        self.websocket.close()

    def send(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.sequence += 1
        command_id = self.sequence
        self.websocket.send(
            json.dumps({"id": command_id, "method": method, "params": params or {}})
        )
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BrowserSmokeError(f"CDP command timed out: {method}")
            message = json.loads(self.websocket.recv(timeout=remaining))
            if message.get("id") != command_id:
                self.events.append(message)
                continue
            if "error" in message:
                raise BrowserSmokeError(
                    f"CDP command failed: {method}: {message['error'].get('message', message['error'])}"
                )
            return message.get("result", {})

    def evaluate(self, expression: str) -> Any:
        response = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if response.get("exceptionDetails"):
            details = response["exceptionDetails"]
            raise BrowserSmokeError(
                f"Browser JavaScript failed: {details.get('text', 'unknown error')}"
            )
        result = response.get("result", {})
        return result.get("value", result.get("description"))

    def wait_for(self, expression: str, *, label: str, timeout: float = 12.0) -> Any:
        deadline = time.monotonic() + timeout
        last_value: Any = None
        while time.monotonic() < deadline:
            last_value = self.evaluate(expression)
            if last_value:
                return last_value
            time.sleep(0.1)
        raise BrowserSmokeError(f"Timed out waiting for {label}; last value={last_value!r}")

    def navigate(self, url: str) -> None:
        self.send("Page.navigate", {"url": url})
        self.wait_for("document.readyState === 'complete'", label=f"page load: {url}")

    def click_exact(self, selector: str, text: str) -> None:
        payload = self.evaluate(
            """
            (() => {
              const selector = %s;
              const text = %s;
              const matches = [...document.querySelectorAll(selector)]
                .filter((element) => (element.textContent || '').trim() === text);
              if (matches.length !== 1) return { ok: false, count: matches.length };
              matches[0].click();
              return { ok: true, count: 1 };
            })()
            """
            % (json.dumps(selector), json.dumps(text))
        )
        if not payload or not payload.get("ok"):
            raise BrowserSmokeError(
                f"Expected one {selector!r} with text {text!r}; found {payload}"
            )

    def fill_input(self, index: int, value: str) -> None:
        payload = self.evaluate(
            """
            (() => {
              const index = %d;
              const inputs = [...document.querySelectorAll('input')];
              const input = inputs[index];
              if (!input) return { ok: false, count: inputs.length };
              const setter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype, 'value'
              ).set;
              setter.call(input, %s);
              input.dispatchEvent(new Event('input', { bubbles: true }));
              input.dispatchEvent(new Event('change', { bubbles: true }));
              return { ok: true, count: inputs.length, type: input.type };
            })()
            """
            % (index, json.dumps(value))
        )
        if not payload or not payload.get("ok"):
            raise BrowserSmokeError(f"Input index {index} is unavailable: {payload}")

    def body_text(self) -> str:
        return str(self.evaluate("document.body?.innerText || ''") or "")

    def screenshot(self, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        result = self.send(
            "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True}
        )
        output_path.write_bytes(base64.b64decode(result["data"]))


def _json_url(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def _create_target(cdp_url: str, initial_url: str) -> dict[str, Any]:
    encoded_url = urllib.parse.quote(initial_url, safe=":/#?=&")
    request = urllib.request.Request(f"{cdp_url}/json/new?{encoded_url}", method="PUT")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def _assert_contains(text: str, expected: str, label: str) -> None:
    if expected not in text:
        raise BrowserSmokeError(f"Missing {label}: {expected!r}")


def _token_contract(client: CdpClient) -> dict[str, Any]:
    return client.evaluate(
        """
        (() => {
          const decode = (token) => {
            const part = token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/');
            return JSON.parse(decodeURIComponent(escape(atob(part))));
          };
          const access = localStorage.getItem('auth_token');
          const refresh = localStorage.getItem('auth_refresh_token');
          const user = JSON.parse(localStorage.getItem('auth_user') || 'null');
          return {
            hasAccess: Boolean(access),
            hasRefresh: Boolean(refresh),
            accessType: access ? decode(access).token_type : null,
            refreshType: refresh ? decode(refresh).token_type : null,
            role: user?.role || null,
          };
        })()
        """
    )


def run_smoke(
    *,
    base_url: str,
    cdp_url: str,
    admin_username: str,
    admin_password: str,
    artifact_dir: Path,
) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    _json_url(f"{cdp_url.rstrip('/')}/json/version")
    target = _create_target(cdp_url.rstrip("/"), f"{base_url}/")
    client = CdpClient(target["webSocketDebuggerUrl"])
    student_username = f"qa_student_{int(time.time())}"
    steps: list[str] = []

    try:
        for domain in ("Page", "Runtime", "Log", "Network"):
            client.send(f"{domain}.enable")

        origin = urllib.parse.urlsplit(base_url)
        client.send(
            "Storage.clearDataForOrigin",
            {
                "origin": f"{origin.scheme}://{origin.netloc}",
                "storageTypes": "all",
            },
        )
        client.navigate(f"{base_url}/")

        client.wait_for(
            "location.hash === '#/login' && document.body?.innerText.includes('登录 HELIX')",
            label="login route",
        )
        client.screenshot(artifact_dir / "01-login-desktop.png")
        steps.append("login_page")

        client.fill_input(0, admin_username)
        client.fill_input(1, admin_password)
        client.click_exact("button", "登录")
        client.wait_for(
            "location.hash === '#/' && document.body?.innerText.includes('班级学情')",
            label="admin home",
        )
        admin_contract = _token_contract(client)
        expected_contract = {
            "hasAccess": True,
            "hasRefresh": True,
            "accessType": "access",
            "refreshType": "refresh",
            "role": "admin",
        }
        if admin_contract != expected_contract:
            raise BrowserSmokeError(f"Unexpected admin token contract: {admin_contract}")
        steps.append("admin_login")

        client.click_exact("a", "班级学情")
        client.wait_for(
            "location.hash === '#/teacher' && document.body?.innerText.includes('班级 ID')",
            label="teacher analytics route",
        )
        client.fill_input(0, "999999")
        client.click_exact("button", "加载学情")
        client.wait_for(
            "document.body?.innerText.includes('该班级暂无在册学生')",
            label="class analytics API response",
        )
        client.screenshot(artifact_dir / "02-teacher-analytics-desktop.png")
        steps.append("teacher_analytics")

        client.click_exact("button", "登出")
        client.wait_for(
            "location.hash === '#/login' && document.body?.innerText.includes('登录 HELIX')",
            label="logout",
        )
        client.click_exact("a", "注册学生账号")
        client.wait_for(
            "location.hash === '#/register' && "
            "document.querySelector('h1')?.textContent.trim() === '注册学生账号' && "
            "document.querySelectorAll('input').length === 3",
            label="register route",
        )
        client.fill_input(0, student_username)
        client.fill_input(1, f"{student_username}@example.com")
        client.fill_input(2, "QaStudent2026")
        client.click_exact("button", "注册并登录")
        client.wait_for(
            "location.hash === '#/' && document.body?.innerText.includes(%s)"
            % json.dumps(student_username),
            label="student home",
        )
        student_text = client.body_text()
        if "班级学情" in student_text:
            raise BrowserSmokeError("Student navigation exposes the teacher analytics entry")
        student_contract = _token_contract(client)
        if student_contract.get("role") != "student":
            raise BrowserSmokeError(f"Unexpected student session: {student_contract}")
        steps.append("student_registration")

        client.navigate(f"{base_url}/#/teacher")
        client.wait_for("location.hash === '#/'", label="student role redirect")
        if "班级学情" in client.body_text():
            raise BrowserSmokeError("Student can still see teacher analytics after direct navigation")
        steps.append("student_route_guard")

        client.send(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": 375,
                "height": 812,
                "deviceScaleFactor": 1,
                "mobile": True,
            },
        )
        client.send("Page.reload")
        client.wait_for("document.readyState === 'complete'", label="mobile reload")
        client.wait_for("location.hash === '#/'", label="mobile home")
        layout = client.evaluate(
            """
            (() => {
              const main = document.querySelector('main')?.getBoundingClientRect();
              const overflow = [...document.querySelectorAll('body *')]
                .filter((element) => {
                  const style = getComputedStyle(element);
                  if (style.display === 'none' || style.visibility === 'hidden') return false;
                  const rect = element.getBoundingClientRect();
                  return rect.width > 0 && (rect.right > innerWidth + 1 || rect.left < -1);
                })
                .slice(0, 10)
                .map((element) => ({
                  tag: element.tagName,
                  text: (element.textContent || '').trim().slice(0, 60),
                  className: String(element.className || '').slice(0, 120),
                }));
              return {
                viewportWidth: innerWidth,
                documentWidth: document.documentElement.scrollWidth,
                mainWidth: main?.width || 0,
                overflow,
              };
            })()
            """
        )
        if layout["documentWidth"] > layout["viewportWidth"] + 1:
            raise BrowserSmokeError(f"Mobile page has horizontal overflow: {layout}")
        if layout["mainWidth"] < 240:
            raise BrowserSmokeError(f"Mobile main content is too narrow: {layout}")
        if layout["overflow"]:
            raise BrowserSmokeError(f"Mobile elements exceed the viewport: {layout}")
        client.screenshot(artifact_dir / "03-student-home-mobile.png")
        steps.append("mobile_layout")

        client.send("Emulation.clearDeviceMetricsOverride")
        uncaught = [
            event
            for event in client.events
            if event.get("method") == "Runtime.exceptionThrown"
        ]
        if uncaught:
            raise BrowserSmokeError(f"Uncaught browser exceptions: {len(uncaught)}")

        return {
            "ok": True,
            "base_url": base_url,
            "steps": steps,
            "student_username": student_username,
            "artifacts": [str(path) for path in sorted(artifact_dir.glob("*.png"))],
        }
    finally:
        client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8012")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9222")
    parser.add_argument(
        "--artifact-dir", type=Path, default=Path("artifacts/browser_qa")
    )
    args = parser.parse_args()

    admin_username = os.environ.get("HELIX_QA_ADMIN_USERNAME", "").strip()
    admin_password = os.environ.get("HELIX_QA_ADMIN_PASSWORD", "")
    if not admin_username or not admin_password:
        raise SystemExit(
            "Set HELIX_QA_ADMIN_USERNAME and HELIX_QA_ADMIN_PASSWORD before running."
        )

    result = run_smoke(
        base_url=args.base_url,
        cdp_url=args.cdp_url,
        admin_username=admin_username,
        admin_password=admin_password,
        artifact_dir=args.artifact_dir.resolve(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
