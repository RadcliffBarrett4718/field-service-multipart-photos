from __future__ import annotations

from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, Field


class DispatchStatus(str, Enum):
    DISPATCHED = "dispatched"
    MEDIA_UPLOADING = "media_uploading"
    AWAITING_TECHNICIAN_FOLLOW_UP = "awaiting_technician_follow_up"


class PhotoUploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=180)
    content_type: str = Field(pattern=r"^image/")
    size_bytes: int = Field(gt=0)
    part_size_bytes: int = Field(default=8 * 1024 * 1024, ge=5 * 1024 * 1024)
    dispatch_status: DispatchStatus
    idempotency_key: str = Field(min_length=8, max_length=128)


class PartUpload(BaseModel):
    part_number: int
    url: str


class PhotoUploadPlan(BaseModel):
    work_order_id: str
    object_key: str
    upload_id: str
    part_size_bytes: int
    parts: list[PartUpload]
    dispatch_status: DispatchStatus


class CompletedPart(BaseModel):
    part_number: int = Field(ge=1)
    etag: str = Field(min_length=1)


class CompletePhotoRequest(BaseModel):
    upload_id: str = Field(min_length=1)
    parts: list[CompletedPart] = Field(min_length=1)
    technician_note: str = Field(min_length=1, max_length=1000)


class FollowUpReceipt(BaseModel):
    work_order_id: str
    object_key: str
    technician_note: str
    dispatch_status: DispatchStatus


def plan_photo_upload(
    infrai: Any,
    bucket: str,
    work_order_id: str,
    request: PhotoUploadRequest,
) -> PhotoUploadPlan:
    if request.dispatch_status is not DispatchStatus.DISPATCHED:
        raise ValueError("Photos can be opened only for a dispatched work order")
    safe_name = PurePosixPath(request.filename).name
    object_key = f"work-orders/{work_order_id}/photos/{request.idempotency_key}-{safe_name}"
    created = infrai.storage.multipart.create(
        bucket,
        {
            "key": object_key,
            "content_type": request.content_type,
            "idempotency_key": request.idempotency_key,
        },
    )
    upload_id = str(created["upload_id"])
    part_count = (request.size_bytes + request.part_size_bytes - 1) // request.part_size_bytes
    parts = [
        PartUpload(
            part_number=number,
            url=str(infrai.storage.multipart.presign_part(upload_id, number)["url"]),
        )
        for number in range(1, part_count + 1)
    ]
    return PhotoUploadPlan(
        work_order_id=work_order_id,
        object_key=object_key,
        upload_id=upload_id,
        part_size_bytes=request.part_size_bytes,
        parts=parts,
        dispatch_status=DispatchStatus.MEDIA_UPLOADING,
    )


def finish_photo_upload(
    infrai: Any,
    work_order_id: str,
    request: CompletePhotoRequest,
) -> FollowUpReceipt:
    completed = infrai.storage.multipart.complete(
        request.upload_id,
        {"parts": [part.model_dump() for part in request.parts]},
    )
    return FollowUpReceipt(
        work_order_id=work_order_id,
        object_key=str(completed["key"]),
        technician_note=request.technician_note,
        dispatch_status=DispatchStatus.AWAITING_TECHNICIAN_FOLLOW_UP,
    )
