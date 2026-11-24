"""Upload the three source CSV files into PostgreSQL and see what is loaded."""
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.schemas.data import UploadOut
from app.services import analytics as an
from app.services import ingest

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/status")
def status(user: CurrentUser, db: DbSession):
    """Rows, date range and last upload for each of the three datasets, plus data-quality notes."""
    return {"datasets": ingest.dataset_status(db), "as_of": an.as_of(db),
            "data_quality": an.data_overview(db).get("data_quality", [])}


@router.post("/upload", response_model=UploadOut)
def upload(user: CurrentUser, db: DbSession, background: BackgroundTasks,
           file: Annotated[UploadFile, File(description="One of the three CSV files")],
           mode: Annotated[Literal["append", "replace"], Form()] = "append",
           dataset: Annotated[str, Form()] = "auto"):
    """Upload a CSV. The dataset is detected from the header. `append` skips ids already stored (safe to repeat);
    `replace` empties that dataset first."""
    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
    result = ingest.ingest_csv(db, data, file.filename or "upload.csv", dataset, mode, user_id=user.id)
    background.add_task(an.warm_cache)      # so the dashboard opens instantly after the upload
    return result


@router.delete("/{dataset}")
def clear(dataset: str, user: CurrentUser, db: DbSession):
    """Delete all rows of one dataset (utility, machine or downtime)."""
    return {"dataset": dataset, "deleted": ingest.clear_dataset(db, dataset)}
