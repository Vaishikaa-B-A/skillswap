# =============================================================
# models.py  –  The Database Schema (Odoo-style architecture)
# =============================================================
# Each class here = one database table.
# SQLAlchemy maps Python objects ↔ database rows automatically.
# =============================================================

import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Float, ForeignKey,
    Table, DateTime, Text, Enum
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func   # func.now() → server-side timestamp

from .database import Base         # the shared declarative base


# =============================================================
# SECTION 1 – ASSOCIATION TABLES  (Many-to-Many bridges)
# =============================================================
# SQLAlchemy needs a plain Table object (not a class) to represent
# a pure join table with no extra columns.

# Links a user to skills they can TEACH
profile_skills_offered = Table(
    "profile_skills_offered",
    Base.metadata,
    Column("profile_id", Integer, ForeignKey("user_profiles.id")),
    Column("skill_id",   Integer, ForeignKey("skill_types.id")),
)

# Links a user to skills they want to LEARN
profile_skills_wanted = Table(
    "profile_skills_wanted",
    Base.metadata,
    Column("profile_id", Integer, ForeignKey("user_profiles.id")),
    Column("skill_id",   Integer, ForeignKey("skill_types.id")),
)

# Links workshop attendees to workshops (many users ↔ many workshops)
workshop_attendees = Table(
    "workshop_attendees",
    Base.metadata,
    Column("workshop_id", Integer, ForeignKey("skill_workshops.id")),
    Column("profile_id",  Integer, ForeignKey("user_profiles.id")),
)


# =============================================================
# SECTION 2 – STATE-MACHINE ENUMS
# =============================================================
# Using Python enums ensures only valid state values are stored.
# str mixin lets FastAPI serialize them as plain strings in JSON.

class SwapState(str, enum.Enum):
    DRAFT       = "draft"        # requester fills in the form
    IN_REVIEW   = "in_review"    # provider has been notified
    MATCHED     = "matched"      # provider accepted
    IN_PROGRESS = "in_progress"  # education is happening
    VALIDATION  = "validation"   # both parties clicked "done"
    CLOSED      = "closed"    
    REJECTED    = "rejected"   

class BountyState(str, enum.Enum):
    OPEN      = "open"       # visible on the community feed
    COMMITTED = "committed"  # a solver has signed up
    COMPLETED = "completed"  # work is done
    SETTLED   = "settled"    # poster released the coins

class WorkshopState(str, enum.Enum):
    OPEN      = "open"       # accepting registrations
    COMMITTED = "committed"  # at least one attendee enrolled
    COMPLETED = "completed"  # session has finished


# =============================================================
# SECTION 3 – CORE DATA MODELS
# =============================================================

class SkillType(Base):
    """
    skill.type  –  Global skill catalogue.
    Think of this as the "master data" table – every skill used
    anywhere in the app (offered, wanted, bounty, workshop)
    references a row in this table.
    """
    __tablename__ = "skill_types"

    id          = Column(Integer, primary_key=True, index=True)
    name        = Column(String(100), unique=True, nullable=False)  # e.g. "Python"
    category    = Column(String(50),  nullable=False)               # "Tech" / "Arts" / "Business"
    description = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Back-references so we can navigate from a skill → its resources/bounties/workshops
    resources  = relationship("SkillResource", back_populates="skill")
    bounties   = relationship("SkillBounty",   back_populates="skill")
    workshops  = relationship("SkillWorkshop", back_populates="skill")


class UserProfile(Base):
    """
    user.profile  –  Central identity in the ecosystem.
    Holds wallet balance (Swap-Coins), reputation score, and
    the many-to-many links to skills offered / wanted.
    """
    __tablename__ = "user_profiles"

    id               = Column(Integer, primary_key=True, index=True)
    username         = Column(String(50),  unique=True, nullable=False)
    email            = Column(String(100), unique=True, nullable=False)
    hashed_password  = Column(String(200), nullable=True)   
    full_name        = Column(String(100), nullable=True)
    wallet_balance   = Column(Float, default=100.0)   # every new user starts with 100 coins
    reputation_score = Column(Float, default=0.0)     # weighted avg of last-10 reviews
    trust_level      = Column(Integer, default=1)     # 1-5, recalculated by reputation engine
    created_at       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Many-to-Many skill links (uses the bridge tables above)
    skills_offered = relationship("SkillType", secondary=profile_skills_offered)
    skills_wanted  = relationship("SkillType", secondary=profile_skills_wanted)

    # One-to-Many: a user can be a requester or provider in many swaps
    swaps_as_requester = relationship(
        "SkillSwap", foreign_keys="SkillSwap.requester_id",
        back_populates="requester"
    )
    swaps_as_provider  = relationship(
        "SkillSwap", foreign_keys="SkillSwap.provider_id",
        back_populates="provider"
    )

    bounties_posted  = relationship("SkillBounty", foreign_keys="SkillBounty.poster_id",
                                    back_populates="poster")
    reviews_given    = relationship("SwapReview",  foreign_keys="SwapReview.reviewer_id",
                                    back_populates="reviewer")
    reviews_received = relationship("SwapReview",  foreign_keys="SwapReview.reviewee_id",
                                    back_populates="reviewee")


# =============================================================
# SECTION 4 – FUNCTIONAL MODELS  ("The Jobs")
# =============================================================

class SkillSwap(Base):
    """
    skill.swap  –  The 1-on-1 barter engine.
    One row = one swap agreement between two users.
    The 'state' column drives the workflow state machine.
    """
    __tablename__ = "skill_swaps"

    id                  = Column(Integer, primary_key=True, index=True)
    requester_id        = Column(Integer, ForeignKey("user_profiles.id"), nullable=False)
    provider_id         = Column(Integer, ForeignKey("user_profiles.id"), nullable=False)
    skill_requested_id  = Column(Integer, ForeignKey("skill_types.id"),   nullable=False)  # what requester WANTS
    skill_offered_id    = Column(Integer, ForeignKey("skill_types.id"),   nullable=False)  # what requester OFFERS
    state               = Column(Enum(SwapState), default=SwapState.DRAFT)
    escrow_amount       = Column(Float, default=0.0)  # coins locked during this swap
    notes               = Column(Text, nullable=True)
    created_at          = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at          = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(timezone.utc))

    requester       = relationship("UserProfile", foreign_keys=[requester_id],
                                   back_populates="swaps_as_requester")
    provider        = relationship("UserProfile", foreign_keys=[provider_id],
                                   back_populates="swaps_as_provider")
    skill_requested = relationship("SkillType",   foreign_keys=[skill_requested_id])
    skill_offered   = relationship("SkillType",   foreign_keys=[skill_offered_id])
    review          = relationship("SwapReview",  back_populates="swap", uselist=False)


class SkillResource(Base):
    """
    skill.resource  –  Community knowledge library.
    Users attach PDFs, videos, and links to a specific SkillType.
    During an active swap (IN_PROGRESS), both parties can share
    resources from this library.
    """
    __tablename__ = "skill_resources"

    id            = Column(Integer, primary_key=True, index=True)
    skill_id      = Column(Integer, ForeignKey("skill_types.id"),    nullable=False)
    uploader_id   = Column(Integer, ForeignKey("user_profiles.id"),  nullable=False)
    title         = Column(String(200), nullable=False)
    resource_type = Column(String(20),  nullable=False)   # "pdf" | "video" | "link"
    url           = Column(String(500), nullable=False)
    description   = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    skill    = relationship("SkillType",   back_populates="resources")
    uploader = relationship("UserProfile")


class SkillBounty(Base):
    """
    skill.bounty  –  Public "Help Wanted" board.
    A user offers Swap-Coins for immediate help with a skill.
    Coins are locked in escrow as soon as the bounty is posted,
    and released to the solver when the poster settles it.
    High-trust posters (trust_level >= 4) get is_highlighted=1
    so their bounties appear at the top of the feed.
    """
    __tablename__ = "skill_bounties"

    id            = Column(Integer, primary_key=True, index=True)
    poster_id     = Column(Integer, ForeignKey("user_profiles.id"), nullable=False)
    skill_id      = Column(Integer, ForeignKey("skill_types.id"),   nullable=False)
    solver_id     = Column(Integer, ForeignKey("user_profiles.id"), nullable=True)  # null until committed
    title         = Column(String(200), nullable=False)
    description   = Column(Text,        nullable=False)
    reward_coins  = Column(Float,        nullable=False)
    state         = Column(Enum(BountyState), default=BountyState.OPEN)
    is_highlighted= Column(Integer, default=0)  # 1 = show at top of feed
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    poster = relationship("UserProfile", foreign_keys=[poster_id], back_populates="bounties_posted")
    solver = relationship("UserProfile", foreign_keys=[solver_id])
    skill  = relationship("SkillType",   back_populates="bounties")


class SkillWorkshop(Base):
    """
    skill.workshop  –  One-to-Many teaching sessions.
    A host creates a session with a seat cap and time slot.
    Attendees join by paying cost_per_seat coins.
    available_seats is a computed property (not stored in DB).
    """
    __tablename__ = "skill_workshops"

    id              = Column(Integer, primary_key=True, index=True)
    host_id         = Column(Integer, ForeignKey("user_profiles.id"), nullable=False)
    skill_id        = Column(Integer, ForeignKey("skill_types.id"),   nullable=False)
    title           = Column(String(200), nullable=False)
    description     = Column(Text,        nullable=False)
    max_seats       = Column(Integer, default=10)
    cost_per_seat   = Column(Float,   default=0.0)   # 0 = free workshop
    scheduled_at    = Column(DateTime(timezone=True), nullable=False)
    state           = Column(Enum(WorkshopState), default=WorkshopState.OPEN)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    host      = relationship("UserProfile")
    skill     = relationship("SkillType", back_populates="workshops")
    attendees = relationship("UserProfile", secondary=workshop_attendees)

    @property
    def available_seats(self) -> int:
        """Dynamically computed – never stored, always fresh."""
        return self.max_seats - len(self.attendees)


# =============================================================
# SECTION 5 – SUPPORT MODELS
# =============================================================

class SwapReview(Base):
    """
    Review submitted after a swap is CLOSED.
    Powers the Reputation Engine: every new review triggers
    a recalculation of the reviewee's weighted reputation_score.
    """
    __tablename__ = "swap_reviews"

    id          = Column(Integer, primary_key=True, index=True)
    swap_id     = Column(Integer, ForeignKey("skill_swaps.id"),    nullable=False)
    reviewer_id = Column(Integer, ForeignKey("user_profiles.id"),  nullable=False)
    reviewee_id = Column(Integer, ForeignKey("user_profiles.id"),  nullable=False)
    rating      = Column(Float,   nullable=False)   # 1.0 – 5.0
    comment     = Column(Text,    nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    swap     = relationship("SkillSwap",   back_populates="review")
    reviewer = relationship("UserProfile", foreign_keys=[reviewer_id], back_populates="reviews_given")
    reviewee = relationship("UserProfile", foreign_keys=[reviewee_id], back_populates="reviews_received")


class EscrowAccount(Base):
    """
    Temporary coin-holding account.
    Created when a swap/bounty starts; destroyed (released or
    refunded) when it ends.  Prevents ghosting by ensuring coins
    are committed BEFORE the education phase begins.
    """
    __tablename__ = "escrow_accounts"

    id           = Column(Integer, primary_key=True, index=True)
    swap_id      = Column(Integer, ForeignKey("skill_swaps.id"),    nullable=True)
    bounty_id    = Column(Integer, ForeignKey("skill_bounties.id"), nullable=True)
    amount       = Column(Float,   nullable=False)
    from_user_id = Column(Integer, ForeignKey("user_profiles.id"),  nullable=False)
    to_user_id   = Column(Integer, ForeignKey("user_profiles.id"),  nullable=False)
    status       = Column(String(20), default="locked")  # "locked" | "released" | "refunded"
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))