# =============================================================
# schemas.py  –  Pydantic Validation Schemas
# =============================================================
# Pydantic schemas are NOT the database models.
# They define:
#   • What JSON the API *accepts*  (Create / Request schemas)
#   • What JSON the API *returns*  (Out / Response schemas)
#
# FastAPI uses these to:
#   1. Automatically validate incoming request bodies.
#   2. Automatically serialize SQLAlchemy objects → JSON responses.
#   3. Auto-generate the /docs Swagger UI.
# =============================================================

from pydantic import BaseModel, field_validator
from typing import List, Optional, Dict, Any
from datetime import datetime

from api.models import SwapState, BountyState, WorkshopState


# ── Skill Type ────────────────────────────────────────────────

class SkillTypeCreate(BaseModel):
    name: str
    category: str          # "Tech" | "Arts" | "Business" | "Language" | etc.
    description: Optional[str] = None

class SkillTypeOut(SkillTypeCreate):
    id: int
    created_at: datetime
    class Config:
        from_attributes = True   # lets Pydantic read SQLAlchemy ORM objects


# ── User Profile ──────────────────────────────────────────────

class UserProfileCreate(BaseModel):
    username:  str
    email:     str
    full_name: Optional[str] = None

class UserProfileOut(BaseModel):
    id:               int
    username:         str
    email:            str
    full_name:        Optional[str]
    wallet_balance:   float
    reputation_score: float
    trust_level:      int
    skills_offered:   List[SkillTypeOut] = []
    skills_wanted:    List[SkillTypeOut] = []
    created_at:       datetime
    class Config:
        from_attributes = True


# ── Skill Swap ────────────────────────────────────────────────

class SwapCreate(BaseModel):
    provider_id:        int
    skill_requested_id: int   # what the requester WANTS to learn
    skill_offered_id:   int   # what the requester OFFERS to teach
    escrow_amount:      float = 0.0
    notes:              Optional[str] = None

class SwapOut(BaseModel):
    id:                 int
    requester_id:       int
    provider_id:        int
    skill_requested_id: int
    skill_offered_id:   int
    state:              SwapState
    escrow_amount:      float
    notes:              Optional[str]
    created_at:         datetime
    class Config:
        from_attributes = True


# ── Skill Resource ────────────────────────────────────────────

class ResourceCreate(BaseModel):
    skill_id:      int
    title:         str
    resource_type: str          # "pdf" | "video" | "link"
    url:           str
    description:   Optional[str] = None

    @field_validator("resource_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        # Ensure only recognised resource types are accepted
        allowed = {"pdf", "video", "link"}
        if v.lower() not in allowed:
            raise ValueError(f"resource_type must be one of: {allowed}")
        return v.lower()

class ResourceOut(ResourceCreate):
    id:          int
    uploader_id: int
    created_at:  datetime
    class Config:
        from_attributes = True


# ── Bounty ────────────────────────────────────────────────────

class BountyCreate(BaseModel):
    skill_id:     int
    title:        str
    description:  str
    reward_coins: float

    @field_validator("reward_coins")
    @classmethod
    def positive_reward(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("reward_coins must be positive")
        return v

class BountyOut(BaseModel):
    id:             int
    poster_id:      int
    skill_id:       int
    title:          str
    description:    str
    reward_coins:   float
    state:          BountyState
    is_highlighted: int
    created_at:     datetime
    class Config:
        from_attributes = True


# ── Workshop ──────────────────────────────────────────────────

class WorkshopCreate(BaseModel):
    skill_id:      int
    title:         str
    description:   str
    max_seats:     int   = 10
    cost_per_seat: float = 0.0
    scheduled_at:  datetime

    @field_validator("max_seats")
    @classmethod
    def positive_seats(cls, v: int) -> int:
        if v < 1:
            raise ValueError("max_seats must be at least 1")
        return v

class WorkshopOut(BaseModel):
    id:            int
    host_id:       int
    skill_id:      int
    title:         str
    description:   str
    max_seats:     int
    cost_per_seat: float
    scheduled_at:  datetime
    state:         WorkshopState
    created_at:    datetime
    class Config:
        from_attributes = True


# ── Review ────────────────────────────────────────────────────

class ReviewCreate(BaseModel):
    swap_id:    int
    reviewee_id:int
    rating:     float        # 1.0 – 5.0
    comment:    Optional[str] = None

    @field_validator("rating")
    @classmethod
    def valid_rating(cls, v: float) -> float:
        if not (1.0 <= v <= 5.0):
            raise ValueError("rating must be between 1.0 and 5.0")
        return round(v, 1)

class ReviewOut(ReviewCreate):
    id:          int
    reviewer_id: int
    created_at:  datetime
    class Config:
        from_attributes = True


# ── Unified Feed Item ─────────────────────────────────────────
# A single schema that can represent a Bounty, Workshop, or Resource
# in the merged community feed endpoint.

class FeedItem(BaseModel):
    type:       str            # "bounty" | "workshop" | "resource"
    id:         int
    title:      str
    description:str
    skill_name: Optional[str]
    created_at: datetime
    extra:      Dict[str, Any] = {}   # type-specific payload (coins, seats, url…)


# ── Match Result ──────────────────────────────────────────────

class DirectMatch(BaseModel):
    id:               int
    username:         str
    reputation_score: float
    trust_level:      int
    skills_offered:   List[str]
    skills_wanted:    List[str]

class CircularMatch(BaseModel):
    user_b:      Dict[str, Any]
    user_c:      Dict[str, Any]
    description: str            # human-readable: "You → B → C → You"

class MatchResult(BaseModel):
    direct_matches:   List[DirectMatch]
    circular_matches: List[CircularMatch]

# ============================================================
# PATCH FOR schemas.py
# ============================================================
# Add these three new schemas anywhere in your schemas.py file.
# A good place is right after the existing UserProfileOut class.
# ============================================================

# from pydantic import BaseModel   ← already at top of your schemas.py


class RegisterRequest(BaseModel):
    """What the browser sends when a user signs up."""
    username:  str
    email:     str
    full_name: str
    password:  str    # plain text — backend will hash it immediately
 
    @field_validator("password")
    @classmethod
    def password_length(cls, v: str) -> str:
        if len(v) < 6:
            raise ValueError("Password must be at least 6 characters")
        return v
 
    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Username must be at least 2 characters")
        if not v.replace("_","").replace("-","").isalnum():
            raise ValueError("Username may only contain letters, numbers, _ and -")
        return v
 
 
class LoginRequest(BaseModel):
    """What the browser sends when a user logs in."""
    username: str    # we log in by username (not email)
    password: str
 
 
class TokenResponse(BaseModel):
    """What the backend returns after a successful login or register."""
    access_token: str   # JWT string — frontend stores this in localStorage
    token_type:   str   # always "bearer"
    user_id:      int
    username:     str
    full_name:    str
    wallet_balance: float
    reputation_score: float
    trust_level: int    

class ContactInfo(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str] = None

    class Config:
        from_attributes = True

class BountyActivityItem(BaseModel):
    id: int
    title: str
    description: Optional[str] = None
    reward_coins: float
    state: str
    poster_id: int
    solver_id: Optional[int] = None
    skill_id: Optional[int] = None
    is_highlighted: int
    created_at: datetime
    contact: Optional[ContactInfo] = None

    class Config:
        from_attributes = True
    