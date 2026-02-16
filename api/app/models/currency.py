from sqlalchemy import BigInteger, Column, Text
from .base import Base

class Currency(Base):
    __tablename__ = "currencies"

    id = Column(BigInteger, primary_key=True)
    code = Column(Text, nullable=False, unique=True)
    name = Column(Text, nullable=True)
