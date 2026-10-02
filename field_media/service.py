from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Iterator

from fastapi import Depends, FastAPI, HTTPException

from .infrai_storage import Infrai, InfraiError, InfraiTransportError, ensure_bucket
from .work_orders import (
    CompletePhotoRequest,
    FollowUpReceipt,
    PhotoUploadPlan,
    PhotoUploadRequest,
    finish_photo_upload,
    plan_photo_upload,
)

BUCKET = os.environ.get("FIELD_MEDIA_BUCKET", "field-service-media")


@asynccontextmanager
async def lifespan(application: FastAPI) -> Iterator[None]:
    application.state.infrai = Infrai()
    ensure_bucket(application.state.infrai, BUCKET)
    yield


app = FastAPI(title="Field media multipart service", lifespan=lifespan)


def get_infrai() -> Infrai:
    return app.state.infrai


def as_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, InfraiError):
        status = exc.status_code if 400 <= exc.status_code < 500 else 502
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, InfraiTransportError):
        return HTTPException(status_code=502, detail="Storage transport error")
    if isinstance(exc, ValueError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=502, detail="Storage response was incomplete")


@app.post("/work-orders/{work_order_id}/photos/multipart", response_model=PhotoUploadPlan)
def open_photo_upload(
    work_order_id: str,
    request: PhotoUploadRequest,
    infrai: Infrai = Depends(get_infrai),
) -> PhotoUploadPlan:
    try:
        return plan_photo_upload(infrai, BUCKET, work_order_id, request)
    except (InfraiError, InfraiTransportError, ValueError, KeyError) as exc:
        raise as_http_error(exc) from exc


@app.post(
    "/work-orders/{work_order_id}/photos/multipart/complete",
    response_model=FollowUpReceipt,
)
def complete_photo_upload(
    work_order_id: str,
    request: CompletePhotoRequest,
    infrai: Infrai = Depends(get_infrai),
) -> FollowUpReceipt:
    try:
        return finish_photo_upload(infrai, work_order_id, request)
    except (InfraiError, InfraiTransportError, ValueError, KeyError) as exc:
        raise as_http_error(exc) from exc
