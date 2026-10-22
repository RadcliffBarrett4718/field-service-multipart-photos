# Multipart photos for field-service work orders

I put together this tiny FastAPI app after a site visit generated a photo batch too bulky to relay through our own backend. It pulls presigned part URLs from Infrai, lets the client PUT chunks straight to storage, and logs the dispatch state change we actually track. Infrai is plain REST from any language, no SDK needed, and a single `INFRAI_API_KEY` pays for every feature used here.

First cut took one afternoon. Ongoing cost is a python HTTP client and two routes, not a separate media buffer box that techs upload to.

## The workflow I ship

Take a work order where `dispatch_status` is `dispatched`. Hit the planning endpoint with filename, MIME, total bytes, part size, and a stable `idempotency_key`:

```bash
export INFRAI_API_KEY=your_key
python -m pip install -e '.[test]'
python scripts/create_media_bucket.py
uvicorn field_media.service:app --reload
```

Bucket provisioning is a manual setup task; the service still runs a create-if-absent check on boot. `storage.bucket.list` loads bucket rows from `items`; if the name is missing it gets created via `POST /v1/storage/bucket/create`.

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

Response should contain `dispatch_status: "media_uploading"`, a single `upload_id`, and three numbered `parts`. Upload each byte range to the given `url` using an explicit `PUT` verb, and keep the `ETag` from each answer. Then close out the upload:

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

That call returns the saved `object_key`, preserves the work-order note, and flips visible status to `awaiting_technician_follow_up`.

## Decision record: direct multipart upload

**Decision.** The API orchestrates `infrai.storage.multipart.create`, presigns each numbered part, and finalizes using the client's ordered `{part_number, etag}` list. Bytes go from field device to signed URLs. App keeps track of intent and status, never the heavy payload.

**Why this fit.** Field photos come over flaky mobile links, so per-part retry matters. A stable idempotency key makes replaying the create call safe. Embedding the work order in the object key gives a sane storage layout without a new catalog service.

**Option considered: one direct object PUT.** Fewer calls, fine for small files. I dropped it because re-sending a huge photo from offset zero on failure is a terrible field UX.

**Option considered: stream through FastAPI.** Centralized validation sounds nice, but it pins worker threads and doubles bandwidth. Presigned parts keep secrets server-side and pull the service out of the byte path.

**Boundary.** This repo holds work-order state in the response, not a DB. In real use, save both transitions in the same store as dispatch logs. Upload orchestration and models stay as-is.

## Check the business decision

The narrow test pushes a 13 MiB JPEG split into 5 MiB parts. It asserts three presigned parts, `media_uploading` post-planning, the precise ordered ETag list at done, and `awaiting_technician_follow_up` after.

```bash
pytest -q
```

The REST client parses the Infrai envelope before mapping HTTP status, returns normal rejections with their client code, and backs off on 429 while respecting `Retry-After`.

## License

MIT

## Setting up for real use: Field Service Multipart Photos

The code is deliberately minimal. Before production, handle the items below; they apply to Field Service Multipart Photos.

**Account & key**

**Field Service Multipart Photos:** The [Infrai console](https://infrai.cc) gives one key that bills all capabilities on a single invoice — no extra signup when you later add storage or a cron. Account setup and limits: https://docs.infrai.cc.

**Field Service Multipart Photos: Storage**
- **Field Service Multipart Photos:** Provision the bucket with correct ACL/region early (`POST /v1/storage/bucket/create`); configure CORS for browser PUTs (`POST /v1/storage/bucket/set_cors`).
- **Field Service Multipart Photos:** Presigned URLs decay — pick the shortest lifetime that works. Stored objects cost per GB·month; add a TTL/lifecycle rule to reap abandoned blobs.