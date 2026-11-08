"""One tiny storage layer: JSON files in Azure Blob Storage, or in a local folder
when STORAGE_CONN is not set. Paths follow the data contract in the README."""
import json
import os
import threading
import uuid
from pathlib import Path

from common import config


_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


class Storage:
    def __init__(self, conn: str | None = None, container: str | None = None, local_dir: str | None = None):
        conn = config.STORAGE_CONN if conn is None else conn
        self.container_name = container or config.STORAGE_CONTAINER
        if conn:
            from azure.storage.blob import BlobServiceClient

            self._cc = BlobServiceClient.from_connection_string(conn).get_container_client(self.container_name)
            try:
                self._cc.create_container()
            except Exception:
                pass  # already exists
            self.kind = "blob"
        else:
            self.root = Path(local_dir or config.LOCAL_DATA_DIR)
            self.root.mkdir(parents=True, exist_ok=True)
            self.kind = "local"

    # -- basic operations ---------------------------------------------------
    def read_json(self, path: str, default=None):
        if self.kind == "blob":
            from azure.core.exceptions import ResourceNotFoundError

            try:
                return json.loads(self._cc.download_blob(path).readall())
            except ResourceNotFoundError:
                return default
        p = self.root / path
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))

    def write_json(self, path: str, obj) -> None:
        data = json.dumps(obj, ensure_ascii=False, default=str)
        if self.kind == "blob":
            from azure.storage.blob import ContentSettings

            self._cc.upload_blob(path, data.encode("utf-8"), overwrite=True,
                                 content_settings=ContentSettings(content_type="application/json"))
            return
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        # unique temp file + atomic rename: readers see the old or the new file, never a half-written one
        tmp = p.with_name(f"{p.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        try:
            tmp.write_text(data, encoding="utf-8")
            tmp.replace(p)
        finally:
            tmp.unlink(missing_ok=True)

    def update_json(self, path: str, change, default=None):
        """Read-modify-write without lost updates. `change(current) -> new` runs under a per-file lock (threads in
        this process); on Blob Storage the write is also conditional on the ETag, retried if another writer won."""
        with _lock_for(f"{self.describe()}|{path}"):
            if self.kind != "blob":
                new = change(self.read_json(path, default=default))
                self.write_json(path, new)
                return new
            from azure.core import MatchConditions
            from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
            from azure.storage.blob import ContentSettings

            blob = self._cc.get_blob_client(path)
            for _ in range(5):
                try:
                    d = blob.download_blob()
                    current, etag = json.loads(d.readall()), d.properties.etag
                except ResourceNotFoundError:
                    current, etag = default, None
                new = change(current)
                data = json.dumps(new, ensure_ascii=False, default=str).encode("utf-8")
                cs = ContentSettings(content_type="application/json")
                try:
                    if etag:
                        blob.upload_blob(data, overwrite=True, etag=etag, match_condition=MatchConditions.IfNotModified,
                                         content_settings=cs)
                    else:
                        blob.upload_blob(data, overwrite=False, content_settings=cs)
                    return new
                except (ResourceModifiedError, ResourceExistsError):
                    continue
            raise RuntimeError(f"Could not save {path}: it kept changing. Please try again.")

    def exists(self, path: str) -> bool:
        if self.kind == "blob":
            return self._cc.get_blob_client(path).exists()
        return (self.root / path).exists()

    def list(self, prefix: str = "") -> list[str]:
        if self.kind == "blob":
            return sorted(b.name for b in self._cc.list_blobs(name_starts_with=prefix))
        base = self.root
        return sorted(str(p.relative_to(base)).replace("\\", "/")
                      for p in base.rglob("*") if p.is_file() and not p.name.endswith(".tmp")
                      and str(p.relative_to(base)).replace("\\", "/").startswith(prefix))

    def describe(self) -> str:
        return f"Azure Blob container '{self.container_name}'" if self.kind == "blob" else f"local folder {self.root}"
