import json
import os

with open(".cartography_jaffle/module_graph.json") as f:
    data = json.load(f)

modules = data.get("modules", [])
edges = data.get("imports_edges", [])
calls_edges = data.get("calls_edges", [])
dead_code = data.get("dead_code_candidates", [])

print("\n--- 1. DEAD CODE (YAML EXCLUDED) ---")
for d in dead_code:
    print("Dead: " + str(d.get("module_path")))
if not dead_code: print("None!")

print("\n--- 2. EVIDENCE LINE NUMBERS ---")
found_zero = sum(1 for e in edges + calls_edges if e.get("evidence", {}).get("line_start") == 0)
print("Edges with line 0: " + str(found_zero))
if edges: print("Sample edge evidence: " + str(edges[0].get("evidence")))

print("\n--- 3. REF() RESOLVES TO ERROR .YML ---")
bad_refs = [e for e in edges if "models/" in e.get("source", "") and e.get("target", "").endswith(".yml")]
for e in bad_refs:
    print("BAD REF: " + e.get("source") + " -> " + e.get("target"))
if not bad_refs: print("None!")

print("\n--- 4. MACRO EDGES ---")
for c in calls_edges:
    print("MACRO CALL: " + c.get("source") + " -> " + c.get("target"))
if not calls_edges: print("None!")
