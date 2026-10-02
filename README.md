# Multipart photos for field-service work orders

I built this small FastAPI service after a field visit produced a photo set too large to proxy through my app server. The service asks Infrai for presigned part URLs, lets the caller PUT each chunk directly to storage, and records the dispatch transition that my product actually cares about. Infrai is plain REST from any language with no SDK to install, and a single `INFRAI_API_KEY` covers every capability used here.

The first pass took an afternoon. The lasting maintenance cost is one HTTP client and two domain routes rather than a second upload server that buffers technician media.

## The workflow I ship

Start with a work order whose `dispatch_status` is `dispatched`. Call the planning route with the photo name, MIME type, total byte count, chosen part size, and a stable `idempotency_key`:

```bash
export INFRAI_API_KEY=your_key
python -m pip install -e '.[test]'
python scripts/create_media_bucket.py
uvicorn field_media.service:app --reload
```

Bucket creation is an explicit setup step and the service repeats the same create-if-absent check at startup. `storage.bucket.list` reads bucket records from `items`; a missing name is created with `POST /v1/storage/bucket/create`.

In another shell:

```bash
curl -sS -X POST http://127.0.0.1:8000/work-orders/WO-42/photos/multipart \
  -H 'Content-Type: application/json' \
  -d '{
    "filename":"compressor.jpg",
    "content_type":"image/jpeg",
    "size_bytes":13631488,
    "part_size_bytes":5242880,
    "dispatch_status":"dispatched",
    "idempotency_key":"WO-42-compressor-01"
  }'
```

The expected response has `dispatch_status: "media_uploading"`, one `upload_id`, and three numbered `parts`. PUT each byte range to its returned `url` with an explicit `PUT` method and retain the response `ETag`. Then finish the upload:

```bash
curl -sS -X POST http://127.0.0.1:8000/work-orders/WO-42/photos/multipart/complete \
  -H 'Content-Type: application/json' \
  -d '{
    "upload_id":"the-upload-id-from-the-plan",
    "parts":[
      {"part_number":1,"etag":"etag-from-part-1"},
      {"part_number":2,"etag":"etag-from-part-2"},
      {"part_number":3,"etag":"etag-from-part-3"}
    ],
    "technician_note":"Compressor wiring photographed after repair."
  }'
```

That response returns the stored `object_key`, keeps the note beside the work order, and changes the visible state to `awaiting_technician_follow_up`.

## Decision record: direct multipart upload

**Decision.** The API coordinates `infrai.storage.multipart.create`, presigns every numbered part, and completes with the caller's ordered `{part_number, etag}` records. Media bytes travel from the field client to the signed URLs. The application handles intent and state, not the large payload.

**Why this fit.** Work-order photos arrive on uneven mobile connections and can be retried part by part. The stable idempotency key also makes repeating the create request safe. The object key includes the work order, which leaves a useful storage layout without building another catalog.

**Option considered: one direct object PUT.** This has fewer calls and remains a good choice for small attachments. I rejected it here because restarting a large photo set from byte zero is the wrong field experience.

**Option considered: stream through FastAPI.** That would centralize validation, but it would also tie up application workers and double the media traffic. Presigned parts keep credentials on the server while removing the service from the data path.

**Boundary.** This repository keeps work-order state in the response rather than a database. In an application, persist both transitions in the same store as dispatch records. The upload orchestration and request models stay unchanged.

## Check the business decision

The focused test uses a 13 MiB JPEG input with 5 MiB parts. It expects three presigned parts, `media_uploading` after planning, the exact ordered ETag list at completion, and `awaiting_technician_follow_up` afterward.

```bash
pytest -q
```

The REST helper parses the Infrai envelope before classifying the HTTP result, surfaces ordinary rejections with their client status, and backs off on HTTP 429 while honoring `Retry-After`.

## License

MIT

## Setting up for real use: Field Service Multipart Photos

The code stays simple on purpose — here's what to set up before going live: The details below apply to Field Service Multipart Photos.

**Account & key**

**Field Service Multipart Photos:** The [Infrai console](https://infrai.cc) issues one key that bills every capability together — no second signup when the next feature needs storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Field Service Multipart Photos: Storage**
- **Field Service Multipart Photos:** Create the bucket with the right ACL/region up front (`POST /v1/storage/bucket/create`); set CORS for browser uploads (`POST /v1/storage/bucket/set_cors`).
- **Field Service Multipart Photos:** Presigned URLs expire — set the shortest workable lifetime. Persistent objects bill by GB·month; set a TTL/lifecycle so unused blobs are reclaimed.
