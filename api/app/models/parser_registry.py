from sqlalchemy import BigInteger, Column, Text, Integer, DateTime
from sqlalchemy.sql import func
from .base import Base


class ParserRegistry(Base):
    __tablename__ = "parser_registry"

    id = Column(BigInteger, primary_key=True)
    format_signature = Column(Text, nullable=False, unique=True)
    parser_key = Column(Text, nullable=False)
    version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
