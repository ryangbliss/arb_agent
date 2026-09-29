"""
Run this from anywhere:
  python3 ~/Desktop/patch.py
"""
import os

BASE = os.path.expanduser("~/Desktop/arb_agent")

# ── 1. Fix Polymarket: remove active filter, fetch more pages ──────────────
poly_path = f"{BASE}/exchanges/polymarket.py"
poly = open(poly_path).read()

# Remove active=true filter that was killing results
poly = poly.replace(
    '{"limit": 200, "active": "true", "closed": "false", "offset": offset}',
    '{"limit": 100, "closed": "false", "offset": offset}'
)
poly = poly.replace(
    '{"limit": 200, "active": "true", "closed": "false", "offset": offset},',
    '{"limit": 100, "closed": "false", "offset": offset},'
)
# Also try removing the limit=500 version from previous patch
poly = poly.replace(
    '{"active": "true", "closed": "false", "limit": 500}',
    '{"limit": 100, "closed": "false", "offset": offset}'
)
# Fix pagination stop condition
poly = poly.replace(
    'if len(batch) < 500 or page >= 6:',
    'if len(batch) < 100 or page >= 30:'
)
poly = poly.replace(
    'if len(batch) < 200 or page >= 15:',
    'if len(batch) < 100 or page >= 30:'
)

open(poly_path, "w").write(poly)
print("✅ Polymarket fixed (removed active filter, up to 3000 markets)")

# ── 2. Fix matching: lower pre-filter threshold, fix scoring ───────────────
match_path = f"{BASE}/matching.py"
match = open(match_path).read()

# Lower keyword pre-filter
match = match.replace(
    "if best_score >= 0.15 and best_poly:",
    "if best_score >= 0.10 and best_poly:"
)
match = match.replace(
    "if best_score >= 0.30 and best_poly:",
    "if best_score >= 0.10 and best_poly:"
)

# Lower det score threshold for direct match
match = match.replace(
    "if det >= confidence_threshold:",
    "if det >= confidence_threshold:"   # keep this one
)

# Lower borderline threshold
match = match.replace(
    "elif det >= 0.20:",
    "elif det >= 0.10:"
)
match = match.replace(
    "elif det >= 0.45:",
    "elif det >= 0.10:"
)

# Fix scoring: weight keyword overlap higher (it was *0.5, make it *0.7)
match = match.replace(
    "score += kw * 0.5",
    "score += kw * 0.70"
)

open(match_path, "w").write(match)
print("✅ Matching fixed (lower thresholds, higher keyword weight)")

# ── 3. Fix .env: lower confidence threshold ────────────────────────────────
env_path = f"{BASE}/.env"
env = open(env_path).read()
for old, new in [
    ("MATCH_CONFIDENCE=0.70", "MATCH_CONFIDENCE=0.30"),
    ("MATCH_CONFIDENCE=0.45", "MATCH_CONFIDENCE=0.30"),
    ("MATCH_CONFIDENCE=0.25", "MATCH_CONFIDENCE=0.30"),
]:
    env = env.replace(old, new)
open(env_path, "w").write(env)
print("✅ .env: MATCH_CONFIDENCE=0.30")

print("\n✅ All patches applied. Now run:")
print("   cd ~/Desktop/arb_agent && python3 main.py")
