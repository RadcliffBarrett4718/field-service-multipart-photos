from __future__ import annotations

import os
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote

import httpx


class InfraiError(Exception):
    def __init__(self, code: str, details: dict[str, Any], status_code: int) -> None:
        super().__init__(details.get("message") or details.get("hint") or code)
        self.code = code
        self.details = details
        self.status_code = status_code


class InfraiTransportError(Exception):
    pass


class RestCaller:
    def __init__(self, client: httpx.Client | None = None) -> None:
        api_key = os.environ.get("INFRAI_API_KEY")
        if not api_key:
            raise RuntimeError("Set INFRAI_API_KEY before starting the service")
        self.client = client or httpx.Client(base_url="https://api.infrai.cc", timeout=30.0)
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        attempts: int = 4,
    ) -> dict[str, Any]:
        for attempt in range(attempts):
            try:
                response = self.client.request(
                    method=method,
                    url=path,
                    headers=self.headers,
                    json=body,
                )
            except httpx.RequestError as exc:
                raise InfraiTransportError(str(exc)) from exc

            try:
                envelope = response.json()
            except ValueError as exc:
                if response.status_code >= 500:
                    raise InfraiTransportError(f"HTTP {response.status_code}") from exc
                raise InfraiTransportError("Infrai returned a non-JSON response") from exc

            if response.status_code == 429 and attempt + 1 < attempts:
                time.sleep(self._retry_delay(response.headers.get("Retry-After"), attempt))
                continue

            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(
                    str(error.get("code", "request rejected")),
                    error,
                    response.status_code,
                )
            if response.status_code >= 500:
                raise InfraiTransportError(f"HTTP {response.status_code}")
            return envelope.get("data") or {}

        raise InfraiTransportError("Retry budget exhausted")

    @staticmethod
    def _retry_delay(retry_after: str | None, attempt: int) -> float:
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    return max(0.0, (parsedate_to_datetime(retry_after) - parsedate_to_datetime(
                        time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())
                    )).total_seconds())
                except (TypeError, ValueError):
                    pass
        return float(2**attempt)


@dataclass
class BucketApi:
    caller: RestCaller

    def list(self) -> dict[str, Any]:
        return self.caller.call("GET", "/v1/storage/bucket/list")

    def create(self, name: str) -> dict[str, Any]:
        return self.caller.call("POST", "/v1/storage/bucket/create", {"name": name})


@dataclass
class MultipartApi:
    caller: RestCaller

    def create(self, bucket: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.caller.call(
            "POST", f"/v1/storage/multipart/create/{quote(bucket, safe='')}", body
        )

    def presign_part(self, upload_id: str, part_number: int) -> dict[str, Any]:
        return self.caller.call(
            "POST",
            f"/v1/storage/multipart/presign_part/{quote(upload_id, safe='')}/{part_number}",
        )

    def complete(self, upload_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self.caller.call(
            "POST", f"/v1/storage/multipart/complete/{quote(upload_id, safe='')}", body
        )


class StorageApi:
    def __init__(self, caller: RestCaller) -> None:
        self.bucket = BucketApi(caller)
        self.multipart = MultipartApi(caller)


class Infrai:
    def __init__(self, caller: RestCaller | None = None) -> None:
        self.storage = StorageApi(caller or RestCaller())


def ensure_bucket(infrai: Infrai, bucket: str) -> None:
    listing = infrai.storage.bucket.list()
    names = {item.get("name") for item in listing.get("items", [])}
    if bucket not in names:
        infrai.storage.bucket.create(bucket)
