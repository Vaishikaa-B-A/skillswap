# SkillSwap – Learning & Resource Ecosystem
## Complete Setup Guide (VS Code → Running App)

---

## What You're Building

A circular-economy skill exchange platform where users trade knowledge instead of money.  
Core features: smart matching · Swap-Coin escrow · bounty board · workshop hub · reputation engine.

---

## File Structure

```
skillswap/
├── database.py      ← DB engine & session factory
├── models.py        ← All SQLAlchemy ORM tables
├── schemas.py       ← Pydantic request/response shapes
├── services.py      ← Business logic (match · escrow · reputation)
├── main.py          ← FastAPI routes (all API endpoints)
├── seed_data.py     ← Test data + full demo workflow
└── requirements.txt ← Python dependencies
```

---

## Step-by-Step Setup (from zero to running)

### STEP 1 – Install Python

1. Go to https://www.python.org/downloads/
2. Download Python **3.11** or higher.
3. During installation, **tick "Add Python to PATH"** (important on Windows).
4. Verify: open a terminal and run `python --version`  
   You should see: `Python 3.11.x` or higher.

---

### STEP 2 – Open the Project in VS Code

1. Open **Visual Studio Code**.
2. Click **File → Open Folder…**
3. Select the `skillswap/` folder you just created.
4. VS Code will show all 7 files in the Explorer panel on the left.

---

### STEP 3 – Open the Integrated Terminal

In VS Code: press `` Ctrl+` `` (backtick) or go to  
**Terminal → New Terminal**

A terminal pane appears at the bottom of VS Code.  
All commands below are typed in this terminal.

---

### STEP 4 – Create a Virtual Environment

A virtual environment keeps your project's packages isolated from other Python projects.

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Mac / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

After activating, your terminal prompt changes to show `(venv)`.  
This means you're inside the virtual environment. ✅

---

### STEP 5 – Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- `fastapi`     – the web framework
- `uvicorn`     – the web server that runs FastAPI
- `sqlalchemy`  – the ORM (Object-Relational Mapper)
- `pydantic`    – data validation

Wait for all packages to finish installing (takes ~30 seconds).

---

### STEP 6 – Start the Server

```bash
uvicorn main:app --reload
```

**What this means:**
- `main`         → use the file `main.py`
- `app`          → find the `app = FastAPI(...)` object inside it
- `--reload`     → auto-restart when you save a file (great for development)

You should see output like:
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
```

A file called `skillswap.db` has also been created in your folder.  
That is your SQLite database – all data lives there.

---

### STEP 7 – Open the Interactive Docs (Swagger UI)

Open your browser and go to:

```
http://127.0.0.1:8000/docs
```

You'll see a beautiful interactive page listing every API endpoint.  
You can click any endpoint, fill in the form, and **try it right from the browser**.

Also available:
```
http://127.0.0.1:8000/redoc    ← Alternative docs (ReDoc style)
```

---

### STEP 8 – Seed the Database with Test Data

Open a **second terminal** (keep the server running in the first one):

```bash
# Make sure venv is still active in this new terminal:
# Windows:  venv\Scripts\activate
# Mac/Linux: source venv/bin/activate

python seed_data.py
```

This will:
1. Create 4 skills (Python, Graphic Design, Spanish, Excel)
2. Create 3 users (Alice, Bob, Carol)
3. Assign skills to each user
4. Upload a learning resource
5. Post a bounty
6. Create a workshop
7. Run a COMPLETE swap workflow from Draft → Closed
8. Submit a peer review

At the end, it prints useful test URLs.

---

## Testing Each Feature

### Test 1 – Smart Matching
```
GET http://127.0.0.1:8000/api/v1/match?user_id=1
```
Alice (user 1) offers Python and wants Design.  
Bob offers Design and wants Python.  
Result: Bob appears as a **direct match** for Alice.

### Test 2 – Community Feed
```
GET http://127.0.0.1:8000/api/v1/feed
```
Returns a unified list of open bounties, upcoming workshops, and recent resources.

### Test 3 – Resource Library
```
GET http://127.0.0.1:8000/api/v1/library/1
```
Returns all resources uploaded for skill ID 1 (Python).

### Test 4 – Bounty Board
```
GET http://127.0.0.1:8000/api/v1/bounties
```
Lists all open bounties, with highlighted ones at the top.

### Test 5 – Workshop List
```
GET http://127.0.0.1:8000/api/v1/workshops
```
Lists upcoming workshops ordered by date.

### Test 6 – User Profile & Wallet
```
GET http://127.0.0.1:8000/api/v1/users/1
```
See Alice's profile, wallet balance, reputation score, and skills.

---

## Understanding the Swap Workflow (State Machine)

```
[Draft] → [In-Review] → [Matched] → [In-Progress] → [Validation] → [Closed]
  ↑           ↑              ↑             ↑                ↑            ↑
  POST     auto-advance   PUT /accept  PUT /start    PUT /validate  PUT /close
initiate                                                              ↓
                                                                   Escrow released
                                                                   Reviews unlocked
```

Each `PUT` call advances the state by one step.  
You cannot skip steps (e.g. you can't close a swap that isn't in Validation).

---

## Understanding the Escrow Flow

```
Requester wallet: 100 coins
                    ↓  (lock_escrow called at /swap/initiate)
Requester wallet:  90 coins     Escrow: 10 coins (status=locked)
                                           ↓  (release_escrow called at /swap/close)
Provider wallet: 110 coins      Escrow: 10 coins (status=released)
```

If the swap is cancelled, `refund_escrow` sends the coins back to the requester.

---

## Understanding the Reputation Engine

After each closed swap, a review can be submitted.  
The engine looks at the last **10 reviews** and calculates a **weighted average**:

```
Review 1 (newest) × weight 10
Review 2          × weight  9
...
Review 10(oldest) × weight  1
─────────────────────────────
Score = sum(rating × weight) / sum(weights)
```

Trust Level tiers:
| Score    | Level | Perk                          |
|----------|-------|-------------------------------|
| ≥ 4.5    | 5     | Top Contributor               |
| ≥ 4.0    | 4     | Bounties highlighted in feed  |
| ≥ 3.0    | 3     | Reliable                      |
| ≥ 2.0    | 2     | Growing                       |
| < 2.0    | 1     | New user                      |

---

## Common Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `ModuleNotFoundError: No module named 'fastapi'` | venv not activated or packages not installed | Run `pip install -r requirements.txt` |
| `Address already in use` | Port 8000 is taken | Run `uvicorn main:app --reload --port 8001` |
| `422 Unprocessable Entity` | Wrong request body format | Check the /docs page for the correct JSON fields |
| `400 Insufficient wallet balance` | User has fewer coins than the escrow amount | Use a smaller escrow_amount (users start with 100 coins) |
| `sqlite3.OperationalError` | DB file locked | Stop the server (Ctrl+C) and restart |

---

## How to Reset the Database

Stop the server, then:
```bash
# Delete the database file
# Windows:
del skillswap.db

# Mac/Linux:
rm skillswap.db
```

Restart the server – a fresh database is created automatically.

---

## Next Steps / Extending the App

1. **Add authentication** – install `python-jose` and `passlib`, add JWT tokens.
2. **Connect a real database** – swap `sqlite:///./skillswap.db` in `database.py`  
   for `postgresql://user:password@localhost/skillswap`.
3. **Add email notifications** – use `fastapi-mail` to notify providers when a swap is requested.
4. **Build a frontend** – create a React or Vue app that calls these endpoints.
5. **Deploy** – push to Railway, Render, or Fly.io for free hosting.
