# =============================================================
# services.py  –  Core Business Logic
# =============================================================
# This file contains the three "engines" of the application.
# Routes in main.py call these functions instead of putting
# business logic directly in the API layer – this separation
# makes the code easier to test and reuse.
#
# ENGINES:
#   1. Smart Match Algorithm   (who should swap with whom?)
#   2. Escrow Service          (lock & release Swap-Coins)
#   3. Reputation Engine       (weighted score + trust levels)
# =============================================================

from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from . import models


# =============================================================
# ENGINE 1 – SMART MATCH ALGORITHM
# =============================================================

def find_direct_matches(db: Session, user_id: int) -> List[models.UserProfile]:
    """
    Diagonal Query:
        Find users where (A.Wants ∩ B.Offers) AND (B.Wants ∩ A.Offers)

    In plain English: find people who can teach me what I want to learn,
    AND who want to learn what I can teach.  Both conditions must be true
    for a "direct match."

    Steps:
        1. Load the current user's skill sets.
        2. Iterate every other user in the system.
        3. For each candidate, check the two intersection conditions.
        4. Return candidates where BOTH are satisfied.

    Time complexity: O(N * S) where N = users, S = skills per user.
    Acceptable for hundreds of users; replace with a SQL query +
    index for thousands.
    """
    user = db.query(models.UserProfile).filter(models.UserProfile.id == user_id).first()
    if not user:
        return []

    # Build sets of skill IDs for fast intersection checks
    my_offered_ids = {s.id for s in user.skills_offered}
    my_wanted_ids  = {s.id for s in user.skills_wanted}

    # Can't match if the user hasn't filled in both sides of their profile
    if not my_offered_ids or not my_wanted_ids:
        return []

    # Load all users except the current one
    candidates = db.query(models.UserProfile).filter(
        models.UserProfile.id != user_id
    ).all()

    direct_matches = []
    for candidate in candidates:
        their_offered_ids = {s.id for s in candidate.skills_offered}
        their_wanted_ids  = {s.id for s in candidate.skills_wanted}

        # Condition 1: they offer at least one thing I want
        they_have_what_i_want = bool(my_wanted_ids & their_offered_ids)

        # Condition 2: they want at least one thing I offer
        they_want_what_i_have = bool(my_offered_ids & their_wanted_ids)

        if they_have_what_i_want and they_want_what_i_have:
            direct_matches.append(candidate)

    # Sort by reputation (best matches first)
    direct_matches.sort(key=lambda u: u.reputation_score, reverse=True)
    return direct_matches


def find_circular_matches(
    db: Session, user_id: int
) -> List[Tuple[models.UserProfile, models.UserProfile]]:
    """
    Circular Swap Fallback:  A → B → C → A

    When no direct 1-on-1 match exists, find a 3-way chain where:
        • A can teach B  (B.Wants ∩ A.Offers)
        • B can teach C  (C.Wants ∩ B.Offers)
        • C can teach A  (A.Wants ∩ C.Offers)

    Returns a list of (user_b, user_c) tuples.
    The caller combines them with user_a to form the complete circle.

    Capped at 5 results to keep response times acceptable.
    """
    user_a = db.query(models.UserProfile).filter(models.UserProfile.id == user_id).first()
    if not user_a:
        return []

    a_offers = {s.id for s in user_a.skills_offered}
    a_wants  = {s.id for s in user_a.skills_wanted}

    all_others = db.query(models.UserProfile).filter(
        models.UserProfile.id != user_id
    ).all()

    circles: List[Tuple[models.UserProfile, models.UserProfile]] = []

    for user_b in all_others:
        b_offers = {s.id for s in user_b.skills_offered}
        b_wants  = {s.id for s in user_b.skills_wanted}

        # A can feed B (B wants something A offers)
        if not (a_offers & b_wants):
            continue   # skip – no A→B link, no point checking C

        for user_c in all_others:
            if user_c.id == user_b.id:
                continue   # B and C must be different people

            c_offers = {s.id for s in user_c.skills_offered}
            c_wants  = {s.id for s in user_c.skills_wanted}

            b_can_feed_c = bool(b_offers & c_wants)   # B→C
            c_can_feed_a = bool(c_offers & a_wants)   # C→A (closes the circle)

            if b_can_feed_c and c_can_feed_a:
                circles.append((user_b, user_c))
                if len(circles) >= 5:               # stop early once we have 5
                    return circles

    return circles


# =============================================================
# ENGINE 2 – ESCROW SERVICE
# =============================================================

def lock_escrow(
    db: Session,
    from_user_id: int,
    to_user_id: int,
    amount: float,
    swap_id:   Optional[int] = None,
    bounty_id: Optional[int] = None,
) -> Optional[models.EscrowAccount]:
    """
    Deduct 'amount' coins from the payer's wallet and create a
    locked EscrowAccount record.

    Returns the EscrowAccount on success, None if the user has
    insufficient funds.

    Why escrow?  Prevents "ghosting" – if coins aren't locked,
    a user could receive a lesson and then refuse to give one back,
    or disappear after accepting a bounty reward.
    """
    from_user = db.query(models.UserProfile).filter(
        models.UserProfile.id == from_user_id
    ).first()

    # Guard: check the user exists AND has enough coins
    if not from_user or from_user.wallet_balance < amount:
        return None

    # Debit the wallet immediately (coins leave the spendable balance)
    from_user.wallet_balance -= amount

    # Create the locked escrow record
    escrow = models.EscrowAccount(
        swap_id=swap_id,
        bounty_id=bounty_id,
        amount=amount,
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        status="locked",
    )
    db.add(escrow)
    db.commit()
    db.refresh(escrow)
    return escrow


def release_escrow(db: Session, escrow_id: int) -> bool:
    """
    Transfer the locked coins from escrow to the intended recipient.

    Called when:
        • A Swap transitions to CLOSED.
        • A Bounty is SETTLED by the poster.

    Returns True on success, False if the escrow record isn't found
    or is already resolved.
    """
    escrow = db.query(models.EscrowAccount).filter(
        models.EscrowAccount.id == escrow_id
    ).first()

    # Only locked escrows can be released
    if not escrow or escrow.status != "locked":
        return False

    to_user = db.query(models.UserProfile).filter(
        models.UserProfile.id == escrow.to_user_id
    ).first()
    if not to_user:
        return False

    # Credit the provider / solver
    to_user.wallet_balance += escrow.amount
    escrow.status = "released"
    db.commit()
    return True


def refund_escrow(db: Session, escrow_id: int) -> bool:
    """
    Return locked coins to the original payer.

    Called when a swap is cancelled before reaching CLOSED,
    or a bounty is retracted.
    """
    escrow = db.query(models.EscrowAccount).filter(
        models.EscrowAccount.id == escrow_id
    ).first()

    if not escrow or escrow.status != "locked":
        return False

    from_user = db.query(models.UserProfile).filter(
        models.UserProfile.id == escrow.from_user_id
    ).first()
    if not from_user:
        return False

    from_user.wallet_balance += escrow.amount
    escrow.status = "refunded"
    db.commit()
    return True


# =============================================================
# ENGINE 3 – REPUTATION ENGINE
# =============================================================

def update_reputation(db: Session, user_id: int) -> None:
    """
    Recalculate a user's reputation_score and trust_level.

    Algorithm: Weighted moving average of the last 10 reviews.
        • The most recent review carries the highest weight.
        • Weight decreases linearly: [10, 9, 8, … 1] for reviews[0..9].
        • This means recent behaviour matters more than old behaviour.

    Trust Level tiers (determines feed highlighting & perks):
        ≥ 4.5  →  Level 5  (Top Contributor)
        ≥ 4.0  →  Level 4  (Trusted)      ← bounties get highlighted
        ≥ 3.0  →  Level 3  (Reliable)
        ≥ 2.0  →  Level 2  (Growing)
        < 2.0  →  Level 1  (New)
    """
    # Fetch last 10 reviews for this user, newest first
    reviews = (
        db.query(models.SwapReview)
        .filter(models.SwapReview.reviewee_id == user_id)
        .order_by(models.SwapReview.created_at.desc())
        .limit(10)
        .all()
    )

    if not reviews:
        return   # no reviews yet; keep default score of 0.0

    # Compute weighted average
    # i=0 (newest) gets weight=N, i=N-1 (oldest) gets weight=1
    total_weight  = 0
    weighted_sum  = 0.0
    n = len(reviews)
    for i, review in enumerate(reviews):
        weight        = n - i          # descending weight
        weighted_sum += review.rating * weight
        total_weight += weight

    new_score = weighted_sum / total_weight  # always between 1.0 and 5.0

    # Determine trust tier
    if new_score >= 4.5:
        trust = 5
    elif new_score >= 4.0:
        trust = 4
    elif new_score >= 3.0:
        trust = 3
    elif new_score >= 2.0:
        trust = 2
    else:
        trust = 1

    # Persist the updated values
    user = db.query(models.UserProfile).filter(models.UserProfile.id == user_id).first()
    if user:
        user.reputation_score = round(new_score, 2)
        user.trust_level      = trust
        db.commit()
