from sqlalchemy import BigInteger, Column, Text, Numeric, Integer, ForeignKey
from sqlalchemy.orm import relationship
from .base import Base


class CreditCardAccount(Base):
    __tablename__ = "credit_card_accounts"

    id = Column(BigInteger, primary_key=True)
    account_id = Column(BigInteger, ForeignKey("accounts.id"), nullable=False, unique=True)
    card_name = Column(Text, nullable=False)
    issuer = Column(Text, nullable=False)
    credit_limit = Column(Numeric(38, 18), nullable=False)
    statement_day = Column(Integer, nullable=False)
    due_day = Column(Integer, nullable=False)

    account = relationship("Account")
