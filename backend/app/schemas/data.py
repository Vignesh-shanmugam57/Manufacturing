import datetime as dt

from pydantic import BaseModel


class UploadOut(BaseModel):
    dataset: str
    label: str
    filename: str | None
    mode: str
    rows_in_file: int
    inserted: int
    duplicates_skipped: int
    invalid_skipped: int
    errors: list[str]
    total_rows: int
    first_ts: dt.datetime | None
    last_ts: dt.datetime | None
