"""Supabase Storage adapter (private bucket). The service-role key never leaves the API; the UI
only ever sees short-lived signed URLs."""
import re
import unicodedata

from ...domain.errors import ExternalServiceError


def safe_key(path):
    """Supabase rejects non-ASCII object keys (e.g. an em dash in a CV filename). Normalise each
    path segment to ASCII letters, digits, '.', '_' and '-'."""
    parts = []
    for seg in path.split("/"):
        ascii_seg = unicodedata.normalize("NFKD", seg).encode("ascii", "ignore").decode()
        ascii_seg = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_seg)
        ascii_seg = re.sub(r"-+\.", ".", ascii_seg).strip("-.") or "file"
        parts.append(ascii_seg[:120])
    return "/".join(parts)


class SupabaseStorage:
    def __init__(self, url, service_role_key, bucket="applications"):
        self.url = url.rstrip("/")
        self.key = service_role_key
        self.bucket_name = bucket
        self._client = None

    def _bucket(self):
        if self._client is None:
            from supabase import create_client
            self._client = create_client(self.url, self.key)
        return self._client.storage.from_(self.bucket_name)

    def _call(self, action, fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001  storage3 raises its own error types
            raise ExternalServiceError(f"Storage {action} failed: {getattr(e, 'message', None) or e}") from e

    def upload(self, path, data, content_type):
        """Returns the key actually used (sanitised), which callers must store."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        key = safe_key(path)
        self._call("upload", lambda: self._bucket().upload(key, data, {"content-type": content_type, "upsert": "true"}))
        return key

    def download(self, path):
        return self._call("download", lambda: self._bucket().download(path))

    def signed_url(self, path, expires_in=300, download_name=None):
        bucket = self._bucket()
        res = self._call("signing", lambda: bucket.create_signed_url(path, expires_in, {"download": download_name})
                         if download_name else bucket.create_signed_url(path, expires_in))
        url = res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
        if url and url.startswith("/"):
            url = f"{self.url}/storage/v1{url}"
        return url
