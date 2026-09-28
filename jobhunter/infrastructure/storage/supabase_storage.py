"""Supabase Storage adapter (private bucket). The service-role key never leaves the API; the UI
only ever sees short-lived signed URLs."""


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

    def upload(self, path, data, content_type):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._bucket().upload(path, data, {"content-type": content_type, "upsert": "true"})
        return path

    def download(self, path):
        return self._bucket().download(path)

    def signed_url(self, path, expires_in=300, download_name=None):
        bucket = self._bucket()
        res = (bucket.create_signed_url(path, expires_in, {"download": download_name}) if download_name
               else bucket.create_signed_url(path, expires_in))
        url = res.get("signedURL") or res.get("signedUrl") or res.get("signed_url")
        if url and url.startswith("/"):
            url = f"{self.url}/storage/v1{url}"
        return url
