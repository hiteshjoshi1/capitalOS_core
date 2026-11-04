from sqlalchemy import JSON, BigInteger, Column, Text, Enum, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func
from .base import Base

ImportStatus = Enum(
    "UPLOADED",
    "IDENTIFIED",
    "PARSED",
    "VALIDATED",
    "IMPORTED",
    "NEEDS_MAPPING",
    "FAILED",
    # Refused before anything was written: wrong account type, or the file names
    # another account (#180).
    "REJECTED",
    # Its rows were removed by "Remove this import" (#180).
    "REMOVED",
    name="import_status",
    create_type=False,
)


class ImportJob(Base):
    __tablename__ = "import_jobs"

    id = Column(BigInteger, primary_key=True)
    account_id = Column(BigInteger, ForeignKey("accounts.id"), nullable=False)
    platform = Column(Text, nullable=False)
    original_filename = Column(Text, nullable=False)
    stored_path = Column(Text, nullable=False)
    file_sha256 = Column(Text, nullable=False)
    format_signature = Column(Text, nullable=True)
    parser_key = Column(Text, nullable=True)
    status = Column(ImportStatus, nullable=False, default="UPLOADED")
    report_path = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # What removing this upload must put back (#180); NULL for jobs imported
    # before migration 074, which can't be removed.
    undo_json = Column(JSON().with_variant(JSONB(), "postgresql"), nullable=True)
    removed_at = Column(DateTime(timezone=True), nullable=True)
