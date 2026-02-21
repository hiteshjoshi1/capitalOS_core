from sqlalchemy import BigInteger, Column, Text, Enum, ForeignKey, DateTime
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
