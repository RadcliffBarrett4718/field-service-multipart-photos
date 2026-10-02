from field_media.work_orders import (
    CompletePhotoRequest,
    DispatchStatus,
    PhotoUploadRequest,
    finish_photo_upload,
    plan_photo_upload,
)


class RecordingMultipart:
    def __init__(self) -> None:
        self.storage = self
        self.multipart = self
        self.created: dict[str, object] = {}
        self.completed: dict[str, object] = {}

    def create(self, bucket: str, body: dict[str, object]) -> dict[str, object]:
        self.created = {"bucket": bucket, **body}
        return {"upload_id": "upload-42"}

    def presign_part(self, upload_id: str, part_number: int) -> dict[str, object]:
        return {"url": f"https://uploads.example/{upload_id}/{part_number}"}

    def complete(self, upload_id: str, body: dict[str, object]) -> dict[str, object]:
        self.completed = {"upload_id": upload_id, **body}
        return {"key": "work-orders/WO-42/photos/visit.jpg"}


def test_photo_flow_changes_dispatch_state_and_presigns_each_part() -> None:
    storage = RecordingMultipart()
    request = PhotoUploadRequest(
        filename="visit.jpg",
        content_type="image/jpeg",
        size_bytes=13 * 1024 * 1024,
        part_size_bytes=5 * 1024 * 1024,
        dispatch_status="dispatched",
        idempotency_key="WO-42-visit-01",
    )

    plan = plan_photo_upload(storage, "field-service-media", "WO-42", request)

    assert plan.dispatch_status is DispatchStatus.MEDIA_UPLOADING
    assert [part.part_number for part in plan.parts] == [1, 2, 3]
    assert storage.created == {
        "bucket": "field-service-media",
        "key": "work-orders/WO-42/photos/WO-42-visit-01-visit.jpg",
        "content_type": "image/jpeg",
        "idempotency_key": "WO-42-visit-01",
    }

    receipt = finish_photo_upload(
        storage,
        "WO-42",
        CompletePhotoRequest(
            upload_id=plan.upload_id,
            parts=[
                {"part_number": 1, "etag": "etag-a"},
                {"part_number": 2, "etag": "etag-b"},
                {"part_number": 3, "etag": "etag-c"},
            ],
            technician_note="Compressor wiring photographed after repair.",
        ),
    )

    assert receipt.dispatch_status is DispatchStatus.AWAITING_TECHNICIAN_FOLLOW_UP
    assert storage.completed["parts"] == [
        {"part_number": 1, "etag": "etag-a"},
        {"part_number": 2, "etag": "etag-b"},
        {"part_number": 3, "etag": "etag-c"},
    ]
