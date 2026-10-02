import os

from field_media.infrai_storage import Infrai, ensure_bucket


bucket = os.environ.get("FIELD_MEDIA_BUCKET", "field-service-media")
ensure_bucket(Infrai(), bucket)
print(f"Bucket ready: {bucket}")
