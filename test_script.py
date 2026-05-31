from app.db.session import SessionLocal
from app.rag.concept_mode import execute_concept_query
db = SessionLocal()
result = execute_concept_query('What is intrinsic value?', db, top_k_chunks=3)
for p in result.best_passages[:2]:
    m = p.get('metadata') or {}
    ctx = m.get('context_text')
    anchor = m.get('anchor_text')
    print('context_text present:', bool(ctx), '| anchor_text present:', bool(anchor))
db.close()
