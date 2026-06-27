from sqlalchemy.orm import Session

from app.portfolio.legacy_backfill import backfill_legacy_positions


def backfill_legacy_positions_for_test(db_engine, *, current_user_id: int = 1) -> None:
    db = Session(bind=db_engine)
    try:
        backfill_legacy_positions(db, current_user_id=current_user_id)
    finally:
        db.close()
