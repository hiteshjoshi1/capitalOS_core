# from fastapi import APIRouter, Depends
# from sqlalchemy import text
# from sqlalchemy.orm import Session
# from app.db.session import get_db

# router = APIRouter()

# @router.get("/meta/schema")
# def schema_meta(db: Session = Depends(get_db)):
#     # minimal check: list some expected tables
#     q = text("""
#       SELECT tablename
#       FROM pg_catalog.pg_tables
#       WHERE schemaname='public'
#       ORDER BY tablename;
#     """)
#     tables = [r[0] for r in db.execute(q).fetchall()]
#     expected = ["accounts", "assets", "transactions", "positions", "prices", "ingestion_jobs", "raw_files"]
#     present = [t for t in expected if t in tables]

#     return {
#         "db": "postgres",
#         "tables_present": present,
#         "table_count": len(tables),
#     }
