"""RS-Sangha INTERNAL score (300 - 900).

This is NOT an official CIBIL score. It is calculated on demand from records that already exist
in this database, for one member at a time. Nothing here is random, mocked or hard-coded per member.

Inputs (all existing tables / columns):
  * users.salary (fallback: the salary on the member's latest fund request)   -> debt / savings ratios
  * member_available_balance_snapshots (daily bank balance, last 90 days)     -> stability + strength
  * contributions (status = Confirmed, last 90 days)                         -> contribution consistency
  * fund_requests + fund_repayments                                           -> repayment history, debt

If a member does not have enough history the function returns status "insufficient_data" and NO score.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.authModal import (
    Contribution,
    FundRepayment,
    FundRequest,
    FundRequestStatus,
    MemberAvailableBalanceSnapshot,
    User,
)

# ---------------------------------------------------------------------------------------------
# Tunable settings (change here, nowhere else)
# ---------------------------------------------------------------------------------------------
SCORE_MIN = 300
SCORE_MAX = 900
LOOKBACK_DAYS = 90

# A score is only produced when the member has at least this much history.
MIN_CONTRIBUTION_DAYS = 14      # confirmed contribution days inside the lookback window
MIN_SNAPSHOT_DAYS = 7           # distinct days with a saved bank-balance snapshot

# Older snapshot rows (saved before the bank_balance sync was deployed) hold a different number.
# Set this to the date you deployed that change so those rows are ignored, e.g. date(2026, 10, 16).
BALANCE_SNAPSHOT_VALID_FROM: date | None = None

DEBT_CAP_MONTHS = 6             # owing 6+ months of salary = worst debt score
TENURE_FULL_DAYS = 180          # history this long = best tenure score
NO_LOAN_HISTORY_SCORE = 0.75    # member has never borrowed: neutral, not perfect
ACTIVE_LOAN_NO_REPAYMENT_SCORE = 0.50   # borrowed, nothing repaid yet

# Weights add up to 1.0
WEIGHTS = {
    "repayment": 0.35,
    "contributions": 0.25,
    "stability": 0.15,
    "strength": 0.10,
    "debt": 0.10,
    "tenure": 0.05,
}
LABELS = {
    "repayment": "Repayment history",
    "contributions": "Contribution consistency",
    "stability": "Balance stability",
    "strength": "Balance vs salary",
    "debt": "Debt burden",
    "tenure": "History length",
}

# (lowest, highest, category) - illustrative RS-Sangha ranges
CATEGORIES = (
    (300, 680, "Subprime"),
    (681, 730, "Near Prime"),
    (731, 770, "Prime"),
    (771, 790, "Prime Plus"),
    (791, 900, "Super Prime"),
)

_IST = timezone(timedelta(hours=5, minutes=30))


def score_category(score: int) -> str:
    for low, high, name in CATEGORIES:
        if low <= score <= high:
            return name
    return CATEGORIES[0][2] if score < SCORE_MIN else CATEGORIES[-1][2]


def _d(value) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _result(*, status: str, score: int | None, missing: list[str], factors: list[dict]) -> dict:
    return {
        "score": score,
        "min_score": SCORE_MIN,
        "max_score": SCORE_MAX,
        "category": score_category(score) if score is not None else None,
        "status": status,
        "missing": missing,
        "calculated_at": datetime.now(timezone.utc),
        "factors": factors,
    }


def calculate_internal_score(db: Session, user: User) -> dict:
    """Calculate the score for ONE member (the row passed in). Read-only: writes nothing."""
    today = datetime.now(_IST).date()
    window_start = today - timedelta(days=LOOKBACK_DAYS - 1)

    # ---- salary already on file (never asked again) ----
    salary = _d(user.salary)
    if salary <= 0:
        latest_salary = (
            db.query(FundRequest.monthly_salary)
            .filter(FundRequest.member_id == user.id)
            .order_by(FundRequest.requested_at.desc(), FundRequest.id.desc())
            .limit(1)
            .scalar()
        )
        salary = _d(latest_salary)

    # ---- confirmed contribution days ----
    contribution_days = {
        row[0]
        for row in db.query(Contribution.for_date)
        .filter(
            Contribution.member_id == user.id,
            Contribution.status == "Confirmed",
            Contribution.for_date >= window_start,
            Contribution.for_date <= today,
        )
        .distinct()
        .all()
    }
    first_contribution_day = (
        db.query(func.min(Contribution.for_date))
        .filter(Contribution.member_id == user.id, Contribution.status == "Confirmed")
        .scalar()
    )

    # ---- daily balance snapshots ----
    snap_filters = [MemberAvailableBalanceSnapshot.member_id == user.id]
    if BALANCE_SNAPSHOT_VALID_FROM is not None:
        snap_filters.append(MemberAvailableBalanceSnapshot.snapshot_day >= BALANCE_SNAPSHOT_VALID_FROM)
    snapshots = (
        db.query(MemberAvailableBalanceSnapshot.snapshot_day, MemberAvailableBalanceSnapshot.balance)
        .filter(
            *snap_filters,
            MemberAvailableBalanceSnapshot.snapshot_day >= window_start,
            MemberAvailableBalanceSnapshot.snapshot_day <= today,
        )
        .all()
    )
    balances = [float(_d(b)) for _, b in snapshots]
    first_snapshot_day = (
        db.query(func.min(MemberAvailableBalanceSnapshot.snapshot_day)).filter(*snap_filters).scalar()
    )

    # ---- is there enough data? ----
    missing: list[str] = []
    if salary <= 0:
        missing.append("Your employment details (monthly salary) are not on file yet.")
    if len(contribution_days) < MIN_CONTRIBUTION_DAYS:
        missing.append(
            f"Needs at least {MIN_CONTRIBUTION_DAYS} confirmed contribution days in the last "
            f"{LOOKBACK_DAYS} days (you have {len(contribution_days)})."
        )
    if len(balances) < MIN_SNAPSHOT_DAYS:
        missing.append(
            f"Needs at least {MIN_SNAPSHOT_DAYS} days of balance history (you have {len(balances)})."
        )
    if missing:
        return _result(status="insufficient_data", score=None, missing=missing, factors=[])

    salary_f = float(salary)

    # ---- 1. repayment history ----
    repayments = db.query(FundRepayment.is_on_time).filter(FundRepayment.member_id == user.id).all()
    loans_taken = (
        db.query(func.count(FundRequest.id))
        .filter(
            FundRequest.member_id == user.id,
            FundRequest.status.in_(
                (FundRequestStatus.disbursed, FundRequestStatus.repaying, FundRequestStatus.completed)
            ),
        )
        .scalar()
        or 0
    )
    if repayments:
        repayment = sum(1 for (on_time,) in repayments if on_time) / len(repayments)
    elif loans_taken == 0:
        repayment = NO_LOAN_HISTORY_SCORE
    else:
        repayment = ACTIVE_LOAN_NO_REPAYMENT_SCORE

    # ---- 2. contribution consistency ----
    first_day = max(first_contribution_day, window_start) if first_contribution_day else window_start
    eligible_days = max((today - first_day).days + 1, 1)
    contributions = _clamp01(len(contribution_days) / eligible_days)

    # ---- 3 + 4. balance stability and strength ----
    average_balance = sum(balances) / len(balances)
    stability = _clamp01(min(balances) / average_balance) if average_balance > 0 else 0.0
    strength = _clamp01(average_balance / salary_f)

    # ---- 5. debt burden (principal still owed on active loans) ----
    active = (
        db.query(FundRequest.id, FundRequest.amount_approved)
        .filter(
            FundRequest.member_id == user.id,
            FundRequest.status.in_((FundRequestStatus.disbursed, FundRequestStatus.repaying)),
        )
        .all()
    )
    repaid = {}
    if active:
        repaid = {
            rid: _d(total)
            for rid, total in db.query(FundRepayment.request_id, func.coalesce(func.sum(FundRepayment.principal), 0))
            .filter(FundRepayment.request_id.in_([a[0] for a in active]))
            .group_by(FundRepayment.request_id)
            .all()
        }
    outstanding = sum((max(_d(amount) - repaid.get(rid, Decimal(0)), Decimal(0)) for rid, amount in active), Decimal(0))
    debt = 1.0 - _clamp01(float(outstanding) / (salary_f * DEBT_CAP_MONTHS))

    # ---- 6. history length ----
    starts = [d for d in (first_contribution_day, first_snapshot_day) if d is not None]
    tenure_days = (today - min(starts)).days + 1 if starts else 0
    tenure = _clamp01(tenure_days / TENURE_FULL_DAYS)

    parts = {
        "repayment": repayment,
        "contributions": contributions,
        "stability": stability,
        "strength": strength,
        "debt": debt,
        "tenure": tenure,
    }
    weighted = sum(WEIGHTS[k] * v for k, v in parts.items()) / sum(WEIGHTS.values())
    score = SCORE_MIN + round((SCORE_MAX - SCORE_MIN) * weighted)
    score = max(SCORE_MIN, min(SCORE_MAX, score))

    factors = [
        {"key": k, "label": LABELS[k], "weight": round(WEIGHTS[k] * 100), "score": round(parts[k] * 100, 1)}
        for k in WEIGHTS
    ]
    return _result(status="sufficient", score=score, missing=[], factors=factors)