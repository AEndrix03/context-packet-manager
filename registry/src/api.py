from __future__ import annotations

import hashlib
import logging
from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse, Response
from botocore.exceptions import ClientError

from settings import RegistrySettings
from database import RegistryDB
from storage import S3Storage

log = logging.getLogger(__name__)


def object_key_for_sha256(sha256: str) -> str:
    return f"blobs/sha256/{sha256}.tar.gz"


def make_app(settings: RegistrySettings) -> FastAPI:
    db = RegistryDB(settings.db_path)
    db.init_schema()

    storage = S3Storage(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key=settings.s3_access_key,
        secret_key=settings.s3_secret_key,
        force_path_style=settings.s3_force_path_style,
    )
    storage.ensure_bucket()

    app = FastAPI(title="CPM Registry", version="0.1.0")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.head("/v1/packages/{name}/{version}")
    def head_exists(name: str, version: str):
        if db.exists(name, version):
            return Response(status_code=200)
        return Response(status_code=404)

    @app.get("/v1/packages/{name}/{version}")
    def get_metadata(name: str, version: str):
        row = db.get_version(name, version)
        if not row:
            raise HTTPException(status_code=404, detail="not found")
        return {
            "name": row.name,
            "version": row.version,
            "sha256": row.sha256,
            "size_bytes": row.size_bytes,
            "object_key": row.object_key,
            "checksum": row.checksum,
            "published_at": row.published_at,
            "yanked": bool(row.yanked),
        }

    @app.get("/v1/packages/{name}")
    def list_package(name: str, include_yanked: bool = False):
        versions = db.list_versions(name, include_yanked=include_yanked)
        return {"name": name, "versions": versions}

    @app.post("/v1/packages/{name}/{version}")
    async def publish(
            name: str,
            version: str,
            request: Request,
            file: UploadFile = File(...),
            overwrite: bool = False,
    ):

        # check if already exists (avoid overwrite)
        if db.exists(name, version):
            if not overwrite:
                raise HTTPException(status_code=409, detail="already exists")
            # overwrite requested → delete previous mapping
            db.delete_version(name, version)

        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="empty upload")

        sha256 = hashlib.sha256(data).hexdigest()
        key = object_key_for_sha256(sha256)

        # upload to S3 (dedup: if already there, ok)
        if storage.head(key) is None:
            try:
                storage.put_bytes(key, data, content_type="application/gzip")
            except ClientError as e:
                log.error(f"S3 upload failed: {e}")
                raise HTTPException(status_code=500, detail="S3 upload failed")

        # insert db mapping
        db.insert_version(
            name=name,
            version=version,
            sha256=sha256,
            size_bytes=len(data),
            object_key=key,
            checksum=None,
            manifest_json=None,
        )

        db.log("publish", package=name, version=version, sha256=sha256, remote=request.client.host if request.client else None)

        return JSONResponse(
            status_code=201,
            content={"ok": True, "name": name, "version": version, "sha256": sha256, "object_key": key, "size_bytes": len(data)},
        )

    @app.get("/v1/packages/{name}/{version}/download")
    def download(name: str, version: str, request: Request):
        row = db.get_version(name, version)
        if not row or row.yanked:
            raise HTTPException(status_code=404, detail="not found")

        body = storage.get_streaming_body(row.object_key)

        db.log("download", package=name, version=version, sha256=row.sha256, remote=request.client.host if request.client else None)

        filename = f"{name}-{version}.tar.gz"
        headers = {"Content-Disposition": f'attachment; filename="{filename}"'}

        return StreamingResponse(body, media_type="application/gzip", headers=headers)

    @app.post("/v1/packages/{name}/{version}/yank")
    def yank(name: str, version: str, request: Request, yanked: bool = True):
        ok = db.yank(name, version, yanked=yanked)
        if not ok:
            raise HTTPException(status_code=404, detail="not found")
        db.log("yank" if yanked else "unyank", package=name, version=version, remote=request.client.host if request.client else None)
        return {"ok": True, "name": name, "version": version, "yanked": yanked}

    return app


# Uvicorn entrypoint: `uvicorn rag.registry.api:app --port 8786`
settings = RegistrySettings.from_env()
app = make_app(settings)

