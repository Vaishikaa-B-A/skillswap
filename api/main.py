# =============================================================
# main.py  –  FastAPI Application Entry Point
# =============================================================
# This file wires together every layer of the application:
#
#   HTTP Request
#       ↓
#   FastAPI Route  (this file)
#       ↓
#   Pydantic Schema  (schemas.py)  – validates input / shapes output
#       ↓
#   SQLAlchemy Session  (database.py)  – talks to skillswap.db
#       ↓
#   ORM Model  (models.py)  – Python object ↔ database row
#       ↓
#   Service Logic  (services.py)  – matching / escrow / reputation
#
# Run with:  uvicorn main:app --reload
# Swagger UI: http://127.0.0.1:8000/docs
# =============================================================

from datetime import datetime, timezone
import token
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session

from api import models, schemas, services
from api.database import engine, get_db

from fastapi.middleware.cors import CORSMiddleware

from api.auth import hash_password, verify_password, create_access_token, decode_token
from fastapi import Header
from api.schemas import RegisterRequest, LoginRequest, TokenResponse
from fastapi.middleware.cors import CORSMiddleware


# Create all tables in skillswap.db on startup (idempotent – safe
# to call every time; existing tables are left untouched).
models.Base.metadata.create_all(bind=engine)

# ── FastAPI instance ──────────────────────────────────────────
app = FastAPI(
    title="SkillSwap  –  Learning & Resource Ecosystem",
    description=(
        "A circular-economy skill-exchange platform with smart matching, "
        "Swap-Coin escrow, a community bounty board, and workshop hub."
    ),
    version="1.0.0",
)

# ONLY ONE MIDDLEWARE BLOCK
app.add_middleware(
    CORSMiddleware,
    # Add your friend's future Netlify URL to this list later
    allow_origins=[
        "http://localhost:5500", 
        "http://127.0.0.1:5500",
        "*" # The asterisk allows ANY site to talk to your API
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# =============================================================
# ── HEALTH CHECK ─────────────────────────────────────────────
# =============================================================

@app.get("/", tags=["Health"])
def root():
    """Quick sanity-check endpoint – confirms the API is running."""
    return {"status": "ok", "message": "SkillSwap API is live 🎉"}


# =============================================================
# ── SKILL TYPES  (Global catalogue) ──────────────────────────
# =============================================================

@app.post("/api/v1/skills", response_model=schemas.SkillTypeOut, tags=["Skills"])
def create_skill(skill: schemas.SkillTypeCreate, db: Session = Depends(get_db)):
    """
    Add a new skill to the global library.
    Raises 400 if a skill with the same name already exists (case-sensitive).
    """
    duplicate = db.query(models.SkillType).filter(
        models.SkillType.name == skill.name
    ).first()
    if duplicate:
        raise HTTPException(status_code=400, detail=f"Skill '{skill.name}' already exists")

    db_skill = models.SkillType(**skill.model_dump())
    db.add(db_skill)
    db.commit()
    db.refresh(db_skill)   # refresh populates auto-generated fields (id, created_at)
    return db_skill


@app.get("/api/v1/skills", response_model=List[schemas.SkillTypeOut], tags=["Skills"])
def list_skills(category: Optional[str] = None, db: Session = Depends(get_db)):
    """
    List all skills in the global catalogue.
    Pass ?category=Tech to filter by category.
    """
    query = db.query(models.SkillType)
    if category:
        query = query.filter(models.SkillType.category == category)
    return query.order_by(models.SkillType.name).all()


# =============================================================
# ── USER PROFILES ─────────────────────────────────────────────
# =============================================================

# Change this: @app.post("/api/v1/users/{user_id}")
# To this:
@app.post("/api/v1/users", response_model=schemas.UserProfileOut)
def create_user(user: schemas.UserProfileCreate, db: Session = Depends(get_db)):
    # Check if username exists
    db_user = db.query(models.UserProfile).filter(models.UserProfile.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # Create the user (ID will be generated automatically)
    new_user = models.UserProfile(**user.dict())
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.get("/api/v1/users/{user_id}", response_model=schemas.UserProfileOut, tags=["Users"])
def get_user(user_id: int, db: Session = Depends(get_db)):
    """Fetch a user's full profile: skills, wallet balance, reputation."""
    user = db.query(models.UserProfile).filter(models.UserProfile.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.post("/api/v1/users/{user_id}/skills/offered/{skill_id}", tags=["Users"])
def add_offered_skill(user_id: int, skill_id: int, db: Session = Depends(get_db)):
    """
    Declare: 'I can teach this skill.'
    Appends the skill to user.skills_offered (the Many-to-Many relation).
    Silently ignores duplicates (idempotent).
    """
    user  = db.query(models.UserProfile).filter(models.UserProfile.id == user_id).first()
    skill = db.query(models.SkillType).filter(models.SkillType.id == skill_id).first()
    if not user or not skill:
        raise HTTPException(status_code=404, detail="User or Skill not found")

    if skill not in user.skills_offered:
        user.skills_offered.append(skill)
        db.commit()
    return {"message": f"'{skill.name}' added to offered skills for {user.username}"}


@app.post("/api/v1/users/{user_id}/skills/wanted/{skill_id}", tags=["Users"])
def add_wanted_skill(user_id: int, skill_id: int, db: Session = Depends(get_db)):
    """
    Declare: 'I want to learn this skill.'
    Appends the skill to user.skills_wanted (the Many-to-Many relation).
    Silently ignores duplicates (idempotent).
    """
    user  = db.query(models.UserProfile).filter(models.UserProfile.id == user_id).first()
    skill = db.query(models.SkillType).filter(models.SkillType.id == skill_id).first()
    if not user or not skill:
        raise HTTPException(status_code=404, detail="User or Skill not found")

    if skill not in user.skills_wanted:
        user.skills_wanted.append(skill)
        db.commit()
    return {"message": f"'{skill.name}' added to wanted skills for {user.username}"}


# =============================================================
# ── DISCOVERY FEED  GET /api/v1/feed ─────────────────────────
# =============================================================

@app.get("/api/v1/feed", response_model=List[schemas.FeedItem], tags=["Discovery"])
def get_feed(db: Session = Depends(get_db)):
    """
    Unified community feed merging Bounties, Workshops, and Resources.

    Ordering logic:
        • Bounties from high-trust posters (is_highlighted=1) rise to the top.
        • Within each type, entries are ordered newest-first.
        • All three types are interleaved into a single list.

    This endpoint is what you'd show on the app's home screen.
    """
    feed: List[schemas.FeedItem] = []

    # ── Bounties (highlighted first, then newest) ────────────
    bounties = (
        db.query(models.SkillBounty)
        .filter(models.SkillBounty.state == models.BountyState.OPEN)
        .order_by(
            models.SkillBounty.is_highlighted.desc(),  # 1 before 0
            models.SkillBounty.created_at.desc()
        )
        .limit(10)
        .all()
    )
    for b in bounties:
        feed.append(schemas.FeedItem(
            type="bounty",
            id=b.id,
            title=b.title,
            description=b.description,
            skill_name=b.skill.name if b.skill else None,
            created_at=b.created_at,
            extra={
                "reward_coins":   b.reward_coins,
                "is_highlighted": bool(b.is_highlighted),
                "poster_id":      b.poster_id,
            },
        ))

    # ── Workshops (soonest first – only future sessions) ─────
    workshops = (
        db.query(models.SkillWorkshop)
        .filter(
            models.SkillWorkshop.state == models.WorkshopState.OPEN,
            models.SkillWorkshop.scheduled_at > datetime.now(timezone.utc),
        )
        .order_by(models.SkillWorkshop.scheduled_at.asc())
        .limit(10)
        .all()
    )
    for w in workshops:
        feed.append(schemas.FeedItem(
            type="workshop",
            id=w.id,
            title=w.title,
            description=w.description,
            skill_name=w.skill.name if w.skill else None,
            created_at=w.created_at,
            extra={
                "available_seats": w.available_seats,
                "scheduled_at":    w.scheduled_at.isoformat(),
                "cost_per_seat":   w.cost_per_seat,
                "host_id":         w.host_id,
            },
        ))

    # ── Resources (newest uploads) ────────────────────────────
    resources = (
        db.query(models.SkillResource)
        .order_by(models.SkillResource.created_at.desc())
        .limit(5)
        .all()
    )
    for r in resources:
        feed.append(schemas.FeedItem(
            type="resource",
            id=r.id,
            title=r.title,
            description=r.description or "",
            skill_name=r.skill.name if r.skill else None,
            created_at=r.created_at,
            extra={
                "resource_type": r.resource_type,
                "url":           r.url,
                "uploader_id":   r.uploader_id,
            },
        ))

    return feed


# =============================================================
# ── SMART MATCH  GET /api/v1/match ───────────────────────────
# =============================================================

@app.get("/api/v1/match", response_model=schemas.MatchResult, tags=["Matching"])
def get_matches(user_id: int, db: Session = Depends(get_db)):
    """
    Run the Smart Match algorithm for the requesting user.

    Flow:
        1. Try the Diagonal Query (direct 1-on-1 matches).
        2. If no direct matches found, fall back to circular A→B→C→A.
        3. Return both lists (circular list will be empty if direct matches exist).

    The frontend should show direct matches first and offer the circular
    option as "expand your network."
    """
    # --- Direct matching ---
    direct_users = services.find_direct_matches(db, user_id)
    direct = [
        schemas.DirectMatch(
            id=u.id,
            username=u.username,
            reputation_score=u.reputation_score,
            trust_level=u.trust_level,
            skills_offered=[s.name for s in u.skills_offered],
            skills_wanted=[s.name for s in u.skills_wanted],
        )
        for u in direct_users
    ]

    # --- Circular fallback (only triggered when no direct match) ---
    circular = []
    if not direct:
        circles = services.find_circular_matches(db, user_id)
        circular = [
            schemas.CircularMatch(
                user_b={"id": b.id, "username": b.username},
                user_c={"id": c.id, "username": c.username},
                description=f"You → {b.username} → {c.username} → You",
            )
            for b, c in circles
        ]

    return schemas.MatchResult(direct_matches=direct, circular_matches=circular)


# =============================================================
# ── RESOURCE LIBRARY ─────────────────────────────────────────
# =============================================================

@app.get("/api/v1/library/{skill_id}", response_model=List[schemas.ResourceOut],
         tags=["Resources"])
def get_library(skill_id: int, db: Session = Depends(get_db)):
    """
    Fetch all community-uploaded resources for a specific skill.
    Use this during an active swap (IN_PROGRESS) to share learning materials.
    """
    # Confirm the skill exists before querying resources
    skill = db.query(models.SkillType).filter(models.SkillType.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")

    return (
        db.query(models.SkillResource)
        .filter(models.SkillResource.skill_id == skill_id)
        .order_by(models.SkillResource.created_at.desc())
        .all()
    )


@app.post("/api/v1/library", response_model=schemas.ResourceOut, tags=["Resources"])
def upload_resource(
    resource: schemas.ResourceCreate,
    uploader_id: int,
    db: Session = Depends(get_db),
):
    """
    Upload a learning resource (PDF link, YouTube video, article URL).
    The resource is tagged to a specific SkillType so it appears
    in the correct section of the library.
    """
    skill    = db.query(models.SkillType).filter(models.SkillType.id == resource.skill_id).first()
    uploader = db.query(models.UserProfile).filter(models.UserProfile.id == uploader_id).first()
    if not skill or not uploader:
        raise HTTPException(status_code=404, detail="Skill or Uploader not found")

    db_resource = models.SkillResource(**resource.model_dump(), uploader_id=uploader_id)
    db.add(db_resource)
    db.commit()
    db.refresh(db_resource)
    return db_resource


# =============================================================
# ── SKILL SWAP WORKFLOW  (1-on-1 barter engine) ──────────────
# =============================================================

@app.post("/api/v1/swap/initiate", response_model=schemas.SwapOut, tags=["Swaps"])
def initiate_swap(
    swap: schemas.SwapCreate,
    requester_id: int,
    db: Session = Depends(get_db),
):
    """
    STEP 1 & 2: DRAFT → IN_REVIEW

    Creates the swap record (DRAFT) then immediately advances it to
    IN_REVIEW (simulating a notification to the provider).

    If escrow_amount > 0, coins are locked right away.  This means
    the requester's wallet balance is reduced immediately – they can't
    back out without a refund request.
    """
    requester = db.query(models.UserProfile).filter(models.UserProfile.id == requester_id).first()
    provider  = db.query(models.UserProfile).filter(models.UserProfile.id == swap.provider_id).first()
    if not requester or not provider:
        raise HTTPException(status_code=404, detail="Requester or Provider not found")
    if requester_id == swap.provider_id:
        raise HTTPException(status_code=400, detail="You cannot swap with yourself")

    # Create in DRAFT state
    db_swap = models.SkillSwap(
        requester_id=requester_id,
        state=models.SwapState.DRAFT,
        **swap.model_dump(),
    )
    db.add(db_swap)
    db.commit()
    db.refresh(db_swap)

    # Lock escrow if a coin amount was specified
    if swap.escrow_amount > 0:
        escrow = services.lock_escrow(
            db=db,
            from_user_id=requester_id,
            to_user_id=swap.provider_id,
            amount=swap.escrow_amount,
            swap_id=db_swap.id,
        )
        if not escrow:
            # Rollback the swap creation too
            db.delete(db_swap)
            db.commit()
            raise HTTPException(status_code=400,
                                detail="Insufficient wallet balance for escrow")

    # Auto-advance: DRAFT → IN_REVIEW
    db_swap.state = models.SwapState.IN_REVIEW
    db.commit()
    db.refresh(db_swap)
    return db_swap


@app.put("/api/v1/swap/{swap_id}/accept", response_model=schemas.SwapOut, tags=["Swaps"])
def accept_swap(swap_id: int, provider_id: int, db: Session = Depends(get_db)):
    """
    STEP 3: IN_REVIEW → MATCHED

    The provider accepts the swap request.
    Only the designated provider can call this endpoint.
    """
    swap = _get_swap_or_404(db, swap_id)
    if swap.provider_id != provider_id:
        raise HTTPException(status_code=403, detail="Only the designated provider can accept")
    _require_state(swap, models.SwapState.IN_REVIEW, "accept")

    swap.state = models.SwapState.MATCHED
    db.commit()
    db.refresh(swap)
    return swap


@app.put("/api/v1/swap/{swap_id}/start", response_model=schemas.SwapOut, tags=["Swaps"])
def start_swap(swap_id: int, db: Session = Depends(get_db)):
    """
    STEP 4: MATCHED → IN_PROGRESS

    Begins the education phase.  Both parties can now share resources
    from the skill library (GET /api/v1/library/{skill_id}).
    """
    swap = _get_swap_or_404(db, swap_id)
    _require_state(swap, models.SwapState.MATCHED, "start")

    swap.state = models.SwapState.IN_PROGRESS
    db.commit()
    db.refresh(swap)
    return swap


@app.put("/api/v1/swap/{swap_id}/validate", response_model=schemas.SwapOut, tags=["Swaps"])
def validate_swap(swap_id: int, db: Session = Depends(get_db)):
    """
    STEP 5: IN_PROGRESS → VALIDATION

    Both parties signal that the exchange is complete.
    In a real app you'd require BOTH users to call this before advancing;
    here we simplify to a single call for demonstration.
    """
    swap = _get_swap_or_404(db, swap_id)
    _require_state(swap, models.SwapState.IN_PROGRESS, "validate")

    swap.state = models.SwapState.VALIDATION
    db.commit()
    db.refresh(swap)
    return swap


@app.put("/api/v1/swap/{swap_id}/close", response_model=schemas.SwapOut, tags=["Swaps"])
def close_swap(swap_id: int, db: Session = Depends(get_db)):
    """
    STEP 6: VALIDATION → CLOSED

    Releases any locked escrow coins to the provider.
    After this, both parties can submit a review via POST /api/v1/reviews.
    """
    swap = _get_swap_or_404(db, swap_id)
    _require_state(swap, models.SwapState.VALIDATION, "close")

    # Release escrow if one was created for this swap
    escrow = db.query(models.EscrowAccount).filter(
        models.EscrowAccount.swap_id == swap_id,
        models.EscrowAccount.status == "locked",
    ).first()
    if escrow:
        services.release_escrow(db, escrow.id)

    swap.state = models.SwapState.CLOSED
    db.commit()
    db.refresh(swap)
    return swap


@app.get("/api/v1/swap/{swap_id}", response_model=schemas.SwapOut, tags=["Swaps"])
def get_swap(swap_id: int, db: Session = Depends(get_db)):
    """Fetch the current state and details of a swap."""
    return _get_swap_or_404(db, swap_id)

@app.get("/api/v1/users", response_model=list[schemas.UserProfileOut], tags=["Users"])
def get_all_users(db: Session = Depends(get_db)):
    """Allows the front-end to FETCH the list of users."""
    return db.query(models.UserProfile).all()

@app.get("/api/v1/users/{user_id}/swaps", response_model=list[schemas.SwapOut], tags=["Swaps"])
def get_user_swaps(user_id: int, db: Session = Depends(get_db)):
    """Fetch all swaps where the user is either the requester or the provider."""
    swaps = db.query(models.SkillSwap).filter(
        (models.SkillSwap.requester_id == user_id) | 
        (models.SkillSwap.provider_id == user_id)
    ).all()
    return swaps


# =============================================================
# ── BOUNTY BOARD ─────────────────────────────────────────────
# =============================================================

@app.post("/api/v1/bounties", response_model=schemas.BountyOut, tags=["Bounties"])
def create_bounty(bounty: schemas.BountyCreate, poster_id: int, db: Session = Depends(get_db)):
    """
    Post a 'Help Wanted' bounty.

    • Reward coins are locked in escrow immediately on creation.
    • If the poster has trust_level >= 4, is_highlighted is set to 1
      so the bounty appears at the top of the community feed.
    """
    poster = _get_user_or_404(db, poster_id)
    if poster.wallet_balance < bounty.reward_coins:
        raise HTTPException(status_code=400, detail="Insufficient wallet balance for bounty reward")

    db_bounty = models.SkillBounty(
        **bounty.model_dump(),
        poster_id=poster_id,
        is_highlighted=1 if poster.trust_level >= 4 else 0,
    )
    db.add(db_bounty)
    db.commit()
    db.refresh(db_bounty)

    # Lock reward coins (to_user_id is self for now; updated when solver commits)
    services.lock_escrow(
        db=db,
        from_user_id=poster_id,
        to_user_id=poster_id,
        amount=bounty.reward_coins,
        bounty_id=db_bounty.id,
    )
    return db_bounty


@app.put("/api/v1/bounties/{bounty_id}/commit", response_model=schemas.BountyOut,
         tags=["Bounties"])
def commit_to_bounty(bounty_id: int, solver_id: int, db: Session = Depends(get_db)):
    """
    A user commits to solving an open bounty.
    Updates the escrow destination so coins will flow to the solver on settlement.
    """
    bounty = db.query(models.SkillBounty).filter(models.SkillBounty.id == bounty_id).first()
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")
    if bounty.state != models.BountyState.OPEN:
        raise HTTPException(status_code=400, detail="Bounty is not open")
    if bounty.poster_id == solver_id:
        raise HTTPException(status_code=400, detail="You cannot solve your own bounty")

    bounty.solver_id = solver_id
    bounty.state     = models.BountyState.COMMITTED

    # Redirect the escrow destination to the actual solver
    escrow = db.query(models.EscrowAccount).filter(
        models.EscrowAccount.bounty_id == bounty_id,
        models.EscrowAccount.status    == "locked",
    ).first()
    if escrow:
        escrow.to_user_id = solver_id

    db.commit()
    db.refresh(bounty)
    return bounty


@app.put("/api/v1/bounties/{bounty_id}/settle", response_model=schemas.BountyOut,
         tags=["Bounties"])
def settle_bounty(bounty_id: int, poster_id: int, db: Session = Depends(get_db)):
    """
    Poster confirms the work is done and releases escrow coins to the solver.
    Only the original poster can call this endpoint.
    """
    bounty = db.query(models.SkillBounty).filter(models.SkillBounty.id == bounty_id).first()
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")
    if bounty.poster_id != poster_id:
        raise HTTPException(status_code=403, detail="Only the poster can settle this bounty")
    if bounty.state != models.BountyState.COMMITTED:
        raise HTTPException(status_code=400, detail="Bounty must be COMMITTED to settle")

    # Release escrow → solver
    escrow = db.query(models.EscrowAccount).filter(
        models.EscrowAccount.bounty_id == bounty_id,
        models.EscrowAccount.status    == "locked",
    ).first()
    if escrow:
        services.release_escrow(db, escrow.id)

    bounty.state = models.BountyState.SETTLED
    db.commit()
    db.refresh(bounty)
    return bounty


@app.get("/api/v1/bounties", response_model=List[schemas.BountyOut], tags=["Bounties"])
def list_bounties(db: Session = Depends(get_db)):
    """List all open bounties (highlighted ones first)."""
    return (
        db.query(models.SkillBounty)
        .filter(models.SkillBounty.state == models.BountyState.OPEN)
        .order_by(models.SkillBounty.is_highlighted.desc(),
                  models.SkillBounty.created_at.desc())
        .all()
    )


# =============================================================
# ── WORKSHOP HUB ─────────────────────────────────────────────
# =============================================================

@app.post("/api/v1/workshops", response_model=schemas.WorkshopOut, tags=["Workshops"])
def create_workshop(
    workshop: schemas.WorkshopCreate,
    host_id: int,
    db: Session = Depends(get_db),
):
    """
    Create a new workshop session.
    The host sets a future date/time, seat cap, and per-seat cost.
    """
    _get_user_or_404(db, host_id)   # ensure host exists

    db_workshop = models.SkillWorkshop(**workshop.model_dump(), host_id=host_id)
    db.add(db_workshop)
    db.commit()
    db.refresh(db_workshop)
    return db_workshop


@app.post("/api/v1/workshop/{workshop_id}/join", tags=["Workshops"])
def join_workshop(workshop_id: int, user_id: int, db: Session = Depends(get_db)):
    """
    Join a workshop if seats are available.

    Checks (in order):
        1. Workshop exists and is OPEN.
        2. Seats are available (available_seats > 0).
        3. User exists and isn't already enrolled.
        4. User has sufficient wallet balance.

    Deducts the seat cost from the user's wallet and adds them
    to the workshop.attendees Many-to-Many relation.
    """
    workshop = db.query(models.SkillWorkshop).filter(
        models.SkillWorkshop.id == workshop_id
    ).first()
    if not workshop:
        raise HTTPException(status_code=404, detail="Workshop not found")
    if workshop.state != models.WorkshopState.OPEN:
        raise HTTPException(status_code=400, detail="Workshop is not open for registration")
    if workshop.available_seats <= 0:
        raise HTTPException(status_code=400, detail="Workshop is fully booked")

    user = _get_user_or_404(db, user_id)
    if user in workshop.attendees:
        raise HTTPException(status_code=400, detail="Already registered for this workshop")
    if user.wallet_balance < workshop.cost_per_seat:
        raise HTTPException(status_code=400,
                            detail=f"Need {workshop.cost_per_seat} coins; you have {user.wallet_balance}")

    # Deduct seat cost
    if workshop.cost_per_seat > 0:
        user.wallet_balance -= workshop.cost_per_seat

    # Add to attendee list (SQLAlchemy handles the bridge table row)
    workshop.attendees.append(user)

    # First attendee moves state to COMMITTED
    if workshop.state == models.WorkshopState.OPEN:
        workshop.state = models.WorkshopState.COMMITTED

    db.commit()
    return {
        "message":         f"Joined '{workshop.title}' successfully!",
        "remaining_seats": workshop.available_seats,
        "wallet_balance":  user.wallet_balance,
    }


@app.get("/api/v1/workshops", response_model=List[schemas.WorkshopOut], tags=["Workshops"])
def list_workshops(db: Session = Depends(get_db)):
    """List upcoming workshops (open or committed), soonest first."""
    return (
        db.query(models.SkillWorkshop)
        .filter(models.SkillWorkshop.state.in_([
            models.WorkshopState.OPEN,
            models.WorkshopState.COMMITTED,
        ]))
        .order_by(models.SkillWorkshop.scheduled_at.asc())
        .all()
    )


# =============================================================
# ── REVIEWS ──────────────────────────────────────────────────
# =============================================================

@app.post("/api/v1/reviews", response_model=schemas.ReviewOut, tags=["Reviews"])
def submit_review(review: schemas.ReviewCreate, reviewer_id: int, db: Session = Depends(get_db)):
    """
    Submit a peer review after a swap is CLOSED.

    Side effects (automatic):
        1. Saves the review row.
        2. Calls services.update_reputation() → recalculates reviewee's
           weighted score and trust_level.
        3. If reviewee's new trust_level >= 4, marks all their open
           bounties as highlighted in the feed.
    """
    swap = _get_swap_or_404(db, review.swap_id)
    if swap.state != models.SwapState.CLOSED:
        raise HTTPException(status_code=400, detail="Reviews can only be submitted for CLOSED swaps")

    # Reviewer must be a participant in the swap
    if reviewer_id not in (swap.requester_id, swap.provider_id):
        raise HTTPException(status_code=403, detail="You were not a participant in this swap")

    db_review = models.SwapReview(
        reviewer_id=reviewer_id,
        **review.model_dump(),
    )
    db.add(db_review)
    db.commit()

    # Trigger reputation engine
    services.update_reputation(db, review.reviewee_id)

    # Auto-highlight bounties for newly-trusted users
    reviewee = db.query(models.UserProfile).filter(
        models.UserProfile.id == review.reviewee_id
    ).first()
    if reviewee and reviewee.trust_level >= 4:
        db.query(models.SkillBounty).filter(
            models.SkillBounty.poster_id == review.reviewee_id,
            models.SkillBounty.state     == models.BountyState.OPEN,
        ).update({"is_highlighted": 1})
        db.commit()

    db.refresh(db_review)
    return db_review


# =============================================================
# ── PRIVATE HELPERS ──────────────────────────────────────────
# =============================================================
# Small DRY helpers used by multiple routes above.

class _ContactInfo:
    """Contact details for a user."""
    id: int
    username: str
    email: str
    full_name: Optional[str]

class _BountyActivityItem:
    """Activity item showing bounty with optional solver/poster contact info."""
    id: int
    title: str
    description: str
    reward_coins: float
    state: str
    poster_id: int
    solver_id: Optional[int]
    skill_id: int
    is_highlighted: int
    created_at: datetime
    contact: Optional[schemas.ContactInfo] = None

@app.get("/api/v1/users/{user_id}/bounties/posted", 
         response_model=List[schemas.BountyActivityItem], # Use the schema here
         tags=["Bounties"])
def get_posted_bounties(user_id: int, db: Session = Depends(get_db)):
    _get_user_or_404(db, user_id)
    bounties = (
        db.query(models.SkillBounty)
        .filter(models.SkillBounty.poster_id == user_id)
        .order_by(models.SkillBounty.created_at.desc())
        .all()
    )
    
    result = []
    for b in bounties:
        contact = None
        if b.solver_id and b.state in (
            models.BountyState.COMMITTED, models.BountyState.SETTLED
        ):
            solver = db.query(models.UserProfile).filter(
                models.UserProfile.id == b.solver_id
            ).first()
            if solver:
                # Use the new schema name
                contact = schemas.ContactInfo(
                    id=solver.id,
                    username=solver.username,
                    email=solver.email,
                    full_name=solver.full_name,
                )
        
        # Use the new schema name
        item = schemas.BountyActivityItem(
            id=b.id, title=b.title, description=b.description,
            reward_coins=b.reward_coins, state=b.state.value if hasattr(b.state, 'value') else b.state,
            poster_id=b.poster_id, solver_id=b.solver_id,
            skill_id=b.skill_id, is_highlighted=b.is_highlighted,
            created_at=b.created_at, contact=contact,
        )
        result.append(item)
    return result


# ── NEW: GET /api/v1/users/{user_id}/bounties/claimed ────────────────────────
@app.get("/api/v1/users/{user_id}/bounties/claimed",
         response_model=List[schemas.BountyActivityItem], tags=["Bounties"])
def get_claimed_bounties(user_id: int, db: Session = Depends(get_db)):
    """
    All bounties claimed (solved) by this user.
    Includes the poster's contact info so the solver can coordinate.
    """
    _get_user_or_404(db, user_id)
    bounties = (
        db.query(models.SkillBounty)
        .filter(models.SkillBounty.solver_id == user_id)
        .order_by(models.SkillBounty.created_at.desc())
        .all()
    )
    result = []
    for b in bounties:
        poster = db.query(models.UserProfile).filter(
            models.UserProfile.id == b.poster_id
        ).first()
        contact = None
        if poster:
            contact = schemas.ContactInfo(
                id=poster.id, username=poster.username,
                email=poster.email, full_name=poster.full_name,
            )
        item = schemas.BountyActivityItem(
            id=b.id, title=b.title, description=b.description,
            reward_coins=b.reward_coins, state=b.state.value if hasattr(b.state, 'value') else b.state,
            poster_id=b.poster_id, solver_id=b.solver_id,
            skill_id=b.skill_id, is_highlighted=b.is_highlighted,
            created_at=b.created_at, contact=contact,
        )
        result.append(item)
    return result


# ── NEW: Poster rejects the committed solver → bounty reopens ─────────────────
@app.put("/api/v1/bounties/{bounty_id}/reject-solver",
         response_model=schemas.BountyOut, tags=["Bounties"])
def reject_bounty_solver(bounty_id: int, poster_id: int, db: Session = Depends(get_db)):
    """
    Poster rejects the current solver.
    Bounty returns to OPEN state so another solver can claim it.
    The escrow destination reverts back to the poster (self-hold) until re-claimed.
    """
    bounty = db.query(models.SkillBounty).filter(models.SkillBounty.id == bounty_id).first()
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")
    if bounty.poster_id != poster_id:
        raise HTTPException(status_code=403, detail="Only the poster can reject a solver")
    if bounty.state != models.BountyState.COMMITTED:
        raise HTTPException(status_code=400, detail="Bounty must be COMMITTED to reject solver")

    # Revert escrow destination back to poster (self-hold until new solver claims)
    escrow = db.query(models.EscrowAccount).filter(
        models.EscrowAccount.bounty_id == bounty_id,
        models.EscrowAccount.status    == "locked",
    ).first()
    if escrow:
        escrow.to_user_id = poster_id

    bounty.solver_id = None
    bounty.state     = models.BountyState.OPEN
    db.commit()
    db.refresh(bounty)
    return bounty

def _get_swap_or_404(db: Session, swap_id: int) -> models.SkillSwap:
    swap = db.query(models.SkillSwap).filter(models.SkillSwap.id == swap_id).first()
    if not swap:
        raise HTTPException(status_code=404, detail=f"Swap {swap_id} not found")
    return swap

# ADD THIS: This route matches the front-end call exactly
@app.get("/api/v1/users/{user_id}/swaps")
def get_user_swaps(user_id: int, db: Session = Depends(get_db)):
    # This finds ALL swaps where the user is either the requester or the provider
    swaps = db.query(models.SkillSwap).filter(
        (models.SkillSwap.requester_id == user_id) | 
        (models.SkillSwap.provider_id == user_id)
    ).all()
    
    if not swaps:
        return [] # Return empty list instead of 404 so the UI doesn't crash
    return swaps


def _get_user_or_404(db: Session, user_id: int) -> models.UserProfile:
    user = db.query(models.UserProfile).filter(models.UserProfile.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user


def _require_state(swap: models.SkillSwap, required: models.SwapState, action: str):
    """Raise a clear 400 error if the swap isn't in the expected state."""
    if swap.state != required:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot '{action}' a swap in state '{swap.state}'. Expected: '{required}'",
        )

@app.post("/api/v1/auth/register", response_model=TokenResponse, tags=["Auth"])
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """
    Create a new account.
 
    Flow:
      1. Check username + email aren't already taken.
      2. Hash the password with bcrypt.
      3. Create the UserProfile row (wallet starts at 100 coins).
      4. Return a JWT token immediately → user is logged in right away.
    """
    # Duplicate check
    existing = db.query(models.UserProfile).filter(
        (models.UserProfile.username == body.username) |
        (models.UserProfile.email    == body.email)
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Username or email is already registered. Please choose another."
        )
 
    # Create user with hashed password. Wallet starts at 100 Swap-Coins.
    print(f"DEBUG: Password length is {len(body.password)}")
# hashed_password = hash_password(body.password)
    new_user = models.UserProfile(
        username        = body.username,
        email           = body.email,
        full_name       = body.full_name,
        hashed_password = hash_password(body.password),   # bcrypt hash
        wallet_balance  = 100.0,                          # welcome bonus
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
 
    # Issue token immediately
    token = create_access_token(new_user.id, new_user.username)
    return TokenResponse(
        access_token   = token,
        token_type     = "bearer",  # Add this here too!
        user_id        = new_user.id,
        username       = new_user.username,
        full_name      = new_user.full_name or "",
        wallet_balance = new_user.wallet_balance,
    )
 
 
# ── REPLACE the /api/v1/auth/login route (clean, single definition) ──────────
@app.post("/api/v1/auth/login", response_model=TokenResponse, tags=["Auth"])
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Log in with username + password, returns JWT token."""
    user = db.query(models.UserProfile).filter(
        models.UserProfile.username == body.username
    ).first()

    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    try:
        if not verify_password(body.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Incorrect username or password.")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid account security format.")

    token = create_access_token(user.id, user.username)
    return TokenResponse(
        access_token     = token,
        token_type       = "bearer",
        user_id          = user.id,
        username         = user.username,
        full_name        = user.full_name or user.username,
        wallet_balance   = user.wallet_balance,
        reputation_score = user.reputation_score,
        trust_level      = user.trust_level,
    )
 
def get_current_user(authorization: str = Header(...), db: Session = Depends(get_db)):
# Reads the 'Authorization: Bearer <token>' header from every request
# and returns the logged-in user, or raises 401 Unauthorized.
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    token   = authorization.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Token expired or invalid. Please log in again.")
    user_id = int(payload["sub"])
    user    = db.query(models.UserProfile).filter(models.UserProfile.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User account not found")
    return user
@app.post("/api/v1/auth/register", response_model=TokenResponse, tags=["Auth"])
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    '''
    Create a new account.
 
    Flow:
      1. Check username/email not already taken.
      2. Hash the plain password with bcrypt.
      3. Create UserProfile row (wallet starts at 100 coins).
      4. Return a JWT token so the browser is immediately logged in.
         No need to visit the login page after signing up.
    '''
    # Check for conflicts on username OR email
    existing = db.query(models.UserProfile).filter(
        (models.UserProfile.username == body.username) |
        (models.UserProfile.email    == body.email)
    ).first()
    if existing:
        raise HTTPException(status_code=400,
            detail="Username or email already taken. Please choose another.")
 
    # Hash password — NEVER store plain text
    hashed = hash_password(body.password)
 
    # Create the user row; wallet_balance defaults to 100.0 (set in models.py)
    new_user = models.UserProfile(
        username        = body.username,
        email           = body.email,
        full_name       = body.full_name,
        hashed_password = hashed,
        wallet_balance  = 100.0,   # 100 Swap-Coins for every new member
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
 
    # Issue token immediately — user is logged in right after registration
    token = create_access_token(new_user.id, new_user.username)
    return TokenResponse(
        access_token   = token,
        token_type     = "bearer",
        user_id        = new_user.id,
        username       = new_user.username,
        full_name      = new_user.full_name or new_user.username,
        wallet_balance = new_user.wallet_balance,
        reputation_score = new_user.reputation_score,
        trust_level      = new_user.trust_level
    )
 
 
