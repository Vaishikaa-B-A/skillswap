# =============================================================
# seed_data.py  –  Populate the DB with test data
# =============================================================
# Run once after starting the server:
#   python seed_data.py
#
# This script makes HTTP calls to your running API.
# Make sure `uvicorn main:app --reload` is running first.
# =============================================================

import requests

BASE = "http://127.0.0.1:8000"

def post(path, body, params=None):
    r = requests.post(f"{BASE}{path}", json=body, params=params)
    r.raise_for_status()
    return r.json()

def put(path, params=None):
    r = requests.put(f"{BASE}{path}", params=params)
    r.raise_for_status()
    return r.json()

print("🌱  Seeding SkillSwap database...\n")

# ── 1. Create Skills ──────────────────────────────────────────
print("Creating skills...")
python   = post("/api/v1/skills", {"name": "Python",         "category": "Tech",     "description": "Python programming"})
design   = post("/api/v1/skills", {"name": "Graphic Design", "category": "Arts",     "description": "Visual design with tools like Figma"})
spanish  = post("/api/v1/skills", {"name": "Spanish",        "category": "Language", "description": "Conversational Spanish"})
excel    = post("/api/v1/skills", {"name": "Excel",          "category": "Business", "description": "Advanced spreadsheets"})

print(f"  ✓ Python (id={python['id']}), Design (id={design['id']}), "
      f"Spanish (id={spanish['id']}), Excel (id={excel['id']})")

# ── 2. Create Users ──────────────────────────────────────────
print("\nCreating users...")
alice = post("/api/v1/users", {"username": "alice", "email": "alice@example.com", "full_name": "Alice Chen"})
bob   = post("/api/v1/users", {"username": "bob",   "email": "bob@example.com",   "full_name": "Bob Ramos"})
carol = post("/api/v1/users", {"username": "carol", "email": "carol@example.com", "full_name": "Carol Smith"})
print(f"  ✓ Alice (id={alice['id']}), Bob (id={bob['id']}), Carol (id={carol['id']})")

# ── 3. Assign Skills ─────────────────────────────────────────
print("\nAssigning skills...")
# Alice: offers Python, wants Design
requests.post(f"{BASE}/api/v1/users/{alice['id']}/skills/offered/{python['id']}").raise_for_status()
requests.post(f"{BASE}/api/v1/users/{alice['id']}/skills/wanted/{design['id']}").raise_for_status()

# Bob: offers Design, wants Python  ← Direct match with Alice!
requests.post(f"{BASE}/api/v1/users/{bob['id']}/skills/offered/{design['id']}").raise_for_status()
requests.post(f"{BASE}/api/v1/users/{bob['id']}/skills/wanted/{python['id']}").raise_for_status()

# Carol: offers Spanish, wants Excel (not a direct match with Alice or Bob – circular only)
requests.post(f"{BASE}/api/v1/users/{carol['id']}/skills/offered/{spanish['id']}").raise_for_status()
requests.post(f"{BASE}/api/v1/users/{carol['id']}/skills/wanted/{excel['id']}").raise_for_status()

print("  ✓ Alice: offers Python | wants Design")
print("  ✓ Bob:   offers Design | wants Python   (direct match with Alice!)")
print("  ✓ Carol: offers Spanish | wants Excel")

# ── 4. Create a Resource ─────────────────────────────────────
print("\nUploading a resource...")
res = post(
    "/api/v1/library",
    {"skill_id": python['id'], "title": "Python Crash Course", "resource_type": "link",
     "url": "https://docs.python.org/3/tutorial/", "description": "Official Python tutorial"},
    params={"uploader_id": alice['id']}
)
print(f"  ✓ Resource '{res['title']}' (id={res['id']})")

# ── 5. Create a Bounty ────────────────────────────────────────
print("\nPosting a bounty...")
bounty = post(
    "/api/v1/bounties",
    {"skill_id": design['id'], "title": "Need a logo for my project",
     "description": "Looking for someone to design a simple logo. Will pay 20 coins.",
     "reward_coins": 20.0},
    params={"poster_id": alice['id']}
)
print(f"  ✓ Bounty '{bounty['title']}' (id={bounty['id']})")

# ── 6. Create a Workshop ─────────────────────────────────────
print("\nCreating a workshop...")
import datetime
future = (datetime.datetime.utcnow() + datetime.timedelta(days=7)).isoformat() + "Z"
workshop = post(
    "/api/v1/workshops",
    {"skill_id": python['id'], "title": "Intro to Python Workshop",
     "description": "A beginner-friendly Python session", "max_seats": 5,
     "cost_per_seat": 5.0, "scheduled_at": future},
    params={"host_id": alice['id']}
)
print(f"  ✓ Workshop '{workshop['title']}' (id={workshop['id']})")

# ── 7. Full Swap Workflow Demo ────────────────────────────────
print("\nRunning a full swap workflow: Alice ↔ Bob...")

swap = post(
    "/api/v1/swap/initiate",
    {"provider_id": bob['id'], "skill_requested_id": design['id'],
     "skill_offered_id": python['id'], "escrow_amount": 10.0,
     "notes": "I'll teach you Python basics in exchange for logo design help!"},
    params={"requester_id": alice['id']}
)
print(f"  ✓ Swap created (id={swap['id']}, state={swap['state']})")

swap = put(f"/api/v1/swap/{swap['id']}/accept", params={"provider_id": bob['id']})
print(f"  ✓ Accepted (state={swap['state']})")

swap = put(f"/api/v1/swap/{swap['id']}/start")
print(f"  ✓ Started (state={swap['state']})")

swap = put(f"/api/v1/swap/{swap['id']}/validate")
print(f"  ✓ Validated (state={swap['state']})")

swap = put(f"/api/v1/swap/{swap['id']}/close")
print(f"  ✓ Closed (state={swap['state']})")

review = post(
    "/api/v1/reviews",
    {"swap_id": swap['id'], "reviewee_id": bob['id'], "rating": 4.8,
     "comment": "Bob was a fantastic design teacher!"},
    params={"reviewer_id": alice['id']}
)
print(f"  ✓ Review submitted (rating={review['rating']})")

print("\n✅  Seeding complete!")
print(f"\n👉  Open http://127.0.0.1:8000/docs to explore the API interactively.")
print(f"    Try: GET /api/v1/match?user_id={alice['id']}  to see Alice's matches.")
print(f"    Try: GET /api/v1/feed  to see the community feed.")
