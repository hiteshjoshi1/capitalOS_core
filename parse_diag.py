import json
import re

def parse():
    with open("/tmp/diag_nick.json") as f:
        content = f.read()
    
    # Extract chunk map from dense_db_results
    chunk_map = {}
    dense_trace_matches = re.findall(r'RAG RETRIEVAL TRACE: dense_db_results --------------\n(\{.*?\})\n-------------- END RAG RETRIEVAL TRACE', content, re.DOTALL)
    for trace_text in dense_trace_matches:
        try:
            trace_json = json.loads(trace_text)
            for chunk in trace_json.get('chunks', []):
                chunk_map[chunk['chunk_id']] = chunk.get('text', '')
        except:
            continue

    # Find the result JSON by finding the last occurrence of something that looks like the result dict
    # Based on the grep, there's a lot of lines. Let's find the last '{' before "candidate_pool_top_results"
    
    # A cleaner way: find the start of the final large JSON block
    # It likely starts after all the RAG RETRIEVAL TRACE blocks
    final_json_start = content.rfind('-------------- END RAG RETRIEVAL TRACE --------------')
    if final_json_start != -1:
        json_text = content[final_json_start + len('-------------- END RAG RETRIEVAL TRACE --------------'):].strip()
        try:
            data = json.loads(json_text)
        except:
            # Maybe there are some extra logs at the end, try to find the start and end of the JSON
            m = re.search(r'(\{.*\})', json_text, re.DOTALL)
            if m:
                try:
                    data = json.loads(m.group(1))
                except:
                    data = None
            else:
                data = None
    else:
        data = None

    if not data:
        print("Could not find/parse the final result JSON.")
        return

    # Use the structure we saw in the tail output
    comparison_results = data.get('comparison_results', [])
    if not comparison_results:
        print("No comparison results found.")
        return
    
    res = comparison_results[0]
    config_a = res.get('config_a', {}) # Baseline
    config_b = res.get('config_b', {}) # Jina
    
    q_a = config_a.get('per_query', [{}])[0]
    q_b = config_b.get('per_query', [{}])[0]

    print("--- Candidate Pool (First 15) ---")
    cp = q_b.get('candidate_pool_top_results', [])
    for i, item in enumerate(cp[:15]):
        cid = item.get('chunk_id')
        txt = chunk_map.get(cid, "Text not found")
        print(f"{i+1}. ID: {cid} | {txt[:100].replace('\n', ' ')}")

    print("\n--- Baseline/Heuristic Top 10 ---")
    bh = q_a.get('top_results', [])
    for i, item in enumerate(bh[:10]):
        cid = item.get('chunk_id')
        txt = chunk_map.get(cid, "Text not found")
        print(f"{i+1}. ID: {cid} | {txt[:100].replace('\n', ' ')}")

    print("\n--- Jina/Raw Top 10 ---")
    jr = q_b.get('top_results', [])
    for i, item in enumerate(jr[:10]):
        cid = item.get('chunk_id')
        txt = chunk_map.get(cid, "Text not found")
        print(f"{i+1}. ID: {cid} | {txt[:100].replace('\n', ' ')}")

    found = any("david attenborough" in t.lower() or "rainforest" in t.lower() for t in chunk_map.values())
    print(f"\nFound 'David Attenborough' or 'rainforest': {found}")

parse()
