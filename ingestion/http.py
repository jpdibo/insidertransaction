from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class TransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class Response:
    body: bytes
    status: int
    headers: dict[str, str]


class HttpClient:
    def __init__(self, *, timeout: float = 20, retries: int = 2, user_agent: str = "InsiderTracker/0.1 private-research"):
        self.timeout = timeout
        self.retries = retries
        self.user_agent = user_agent
        self.ssl_context = ssl.create_default_context()
        if hasattr(ssl, "enum_certificates"):
            for certificate, encoding, trust in ssl.enum_certificates("ROOT"):
                if encoding == "x509_asn" and (trust is True or "1.3.6.1.5.5.7.3.1" in trust):
                    try:
                        self.ssl_context.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(certificate))
                    except ssl.SSLError:
                        continue

    def request(self, url: str, *, method: str = "GET", expected_host: str,
                json_body: dict | None = None, headers: dict[str, str] | None = None) -> Response:
        if not url.startswith(f"https://{expected_host}/"):
            raise TransportError(f"refusing unexpected host: {url}")
        request_headers = {"User-Agent": self.user_agent, "Accept": "*/*", **(headers or {})}
        body = None
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=body, method=method, headers=request_headers)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout, context=self.ssl_context) as response:
                    final_url = response.geturl()
                    if not final_url.startswith(f"https://{expected_host}/"):
                        raise TransportError(f"refusing redirect to unexpected host: {final_url}")
                    return Response(response.read(), response.status, {key.lower(): value for key, value in response.headers.items()})
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt == self.retries:
                    raise TransportError(f"HTTP {exc.code} for {url}") from exc
                retry_after = exc.headers.get("Retry-After")
                delay = min(float(retry_after), 30) if retry_after and retry_after.isdigit() else attempt + 1
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt == self.retries:
                    raise TransportError(f"transport failure for {url}: {exc}") from exc
                time.sleep(attempt + 1)
        raise TransportError(f"request failed: {last_error}")

    def parse_json(self, response: Response) -> dict:
        content_type = response.headers.get("content-type", "").lower()
        if "json" not in content_type or response.body.lstrip().startswith(b"<"):
            raise TransportError(f"expected JSON but received {content_type or 'unknown MIME'}")
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise TransportError("invalid JSON response") from exc
        header = payload.get("header", {})
        if header.get("result.val") != 0 or header.get("http.code") != 200:
            raise TransportError(f"application error response: {header}")
        return payload

    def json(self, url: str, *, method: str, expected_host: str) -> dict:
        return self.parse_json(self.request(url, method=method, expected_host=expected_host))
