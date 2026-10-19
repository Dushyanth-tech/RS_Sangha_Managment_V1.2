"""RS-Sangha INTERNAL credit score (300 - 900).

This is NOT an official CIBIL / TransUnion score and does not use their algorithm. It is calculated
on demand, for one member at a time, from records that already exist in this database. Nothing is
random, mocked or hard-coded per member, and nothing is written.

HOW IT WORKS (day-one tracking)
-------------------------------
There is NO minimum number of days before a score is calculated. Every request re-reads the
latest records, so a loan disbursed today is reflected on the very next calculation.

The score is built from five factors. Each factor is either
  * "calculated"    - there is real evidence for it, or
  * "insufficient"  - there is not enough evidence yet. It is then LEFT OUT of the score: it is never
                      scored as zero (bad behaviour) and never given full points.

  factor          weight  evidence used
  --------------  ------  ----------------------------------------------------------------------
  repayment        40 %   fund_repayments (is_on_time flag) + monthly interest cycles that are past
                          their due date and still unpaid
  contributions    25 %   confirmed contribution days since the member's first confirmed day
  stability        15 %   lowest vs average daily balance snapshot (needs snapshots from 2+ days)
  strength         10 %   average snapshot balance vs monthly salary (works from ONE snapshot)
  debt             10 %   principal still owed on active loans vs monthly salary

  score = 300 + 600 * (sum(weight * factor) / sum(weight of calculated factors))

DATA SUFFICIENCY
----------------
  coverage = total weight of the calculated factors
  insufficient_data : coverage < MIN_COVERAGE_FOR_SCORE        -> no score is returned
  provisional       : a score exists, but too little evidence to call it reliable -> no category
  sufficient        : the factors worth >= RELIABLE_COVERAGE each have enough evidence
                      (see RELIABLE_* constants). A category is only given here.

LOAN DUE DATES
--------------
The loan tables hold no repayment schedule, so due dates are DERIVED from existing fields: interest
(INTEREST_RATE_PERCENT of the outstanding principal) falls due every calendar month counting from
fund_requests.disbursed_at. A cycle is "overdue" only when its due date has passed AND the total
interest paid so far (fund_repayments.interest) is still below the interest owed up to that cycle.
Nothing is overdue before its due date.
"""
from __future__ import annotations

import calendar
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
# Settings (change here, nowhere else)
# ---------------------------------------------------------------------------------------------
SCORE_MIN = 300
SCORE_MAX = 900

# Upper bound on how far back contributions / snapshots are read (keeps the query small).
# It is a cap, not a minimum: a member with 1 day of history is scored from that 1 day.
HISTORY_CAP_DAYS = 365

# A factor about "consistency" needs at least this many observed days to say anything.
MIN_DAYS_FOR_CONSISTENCY = 2

MIN_COVERAGE_FOR_SCORE = 0.20   # below this much evidence there is no score at all
RELIABLE_COVERAGE = 0.75        # reliable weight needed for status "sufficient"

# Evidence a factor needs before it counts towards a RELIABLE (categorised) score.
# These never block the score itself - they only decide "provisional" vs "sufficient".
RELIABLE_REPAYMENT_EVIDENCE = 3     # recorded repayments + missed due dates
RELIABLE_CONTRIBUTION_DAYS = 14
RELIABLE_STABILITY_DAYS = 7
RELIABLE_STRENGTH_DAYS = 3

# Snapshots saved before the bank_balance sync was deployed hold a different number.
# Set to the deployment date (e.g. date(2026, 10, 16)) to ignore them.
BALANCE_SNAPSHOT_VALID_FROM: date | None = None

DEBT_CAP_MONTHS = 6     # owing 6+ months of salary = lowest debt factor

WEIGHTS = {
    "repayment": 0.40,
    "contributions": 0.25,
    "stability": 0.15,
    "strength": 0.10,
    "debt": 0.10,
}
LABELS = {
    "repayment": "Repayment history",
    "contributions": "Contribution consistency",
    "stability": "Balance stability",
    "strength": "Balance vs salary",
    "debt": "Debt burden",
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
_PAISA = Decimal("0.01")


def score_category(score: int) -> str:
    for low, high, name in CATEGORIES:
        if low <= score <= high:
            return name
    return CATEGORIES[0][2] if score < SCORE_MIN else CATEGORIES[-1][2]


# ---------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------
def _d(value) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _rupees(x) -> str:
    return f"₹{float(x):,.0f}"


def _add_months(dt: datetime, months: int) -> datetime:
    index = dt.month - 1 + months
    year, month = dt.year + index // 12, index % 12 + 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))


def _factor(key: str, *, score: float | None, detail: str, reliable: bool = False) -> dict:
    calculated = score is not None
    return {
        "key": key,
        "label": LABELS[key],
        "weight": round(WEIGHTS[key] * 100),
        "status": "calculated" if calculated else "insufficient",
        "score": round(score * 100, 1) if calculated else None,   # display only
        "raw": score,                                              # exact value used in the maths
        "reliable": bool(calculated and reliable),
        "detail": detail,
    }


def _loan_cycles(loan: FundRequest, reps: list, rate: Decimal, now: datetime) -> tuple[int, int, datetime | None]:
    """Derive (cycles_due, cycles_overdue, next_due_date) for one loan from its existing records."""
    start_dt = loan.disbursed_at
    if start_dt is None:
        return 0, 0, None
    approved = _d(loan.amount_approved)
    limit = min(now, loan.completed_at) if loan.completed_at else now   # duties end at completion
    interest_paid = sum((_d(r.interest) for r in reps), Decimal(0))

    expected = Decimal(0)
    due_count = overdue_count = 0
    next_due = None
    k = 1
    while k <= 600:
        window_start = _add_months(start_dt, k - 1)
        due = _add_months(start_dt, k)
        if due > limit:                       # not due yet -> NOT overdue
            next_due = None if loan.completed_at else due
            break
        principal_before = sum((_d(r.principal) for r in reps if r.paid_at < window_start), Decimal(0))
        outstanding = max(approved - principal_before, Decimal(0))
        if outstanding <= 0:
            break
        expected += (outstanding * rate / 100).quantize(_PAISA)
        due_count += 1
        if interest_paid + _PAISA < expected:  # due date passed and interest still short
            overdue_count += 1
        k += 1
    return due_count, overdue_count, next_due


def calculate_internal_score(db: Session, user: User, interest_rate_percent: Decimal) -> dict:
    """Score for ONE member (the row passed in). Read-only."""
    now = datetime.utcnow()                          # naive UTC, like the loan tables
    now_aware = datetime.now(timezone.utc)
    today = datetime.now(_IST).date()
    cap_start = today - timedelta(days=HISTORY_CAP_DAYS - 1)
    rate = _d(interest_rate_percent)

    # ---- salary already on file (never asked again) ----
    salary = _d(user.salary)
    if salary <= 0:
        salary = _d(
            db.query(FundRequest.monthly_salary)
            .filter(FundRequest.member_id == user.id)
            .order_by(FundRequest.requested_at.desc(), FundRequest.id.desc())
            .limit(1)
            .scalar()
        )
    have_salary = salary > 0

    # ---- loans + repayments (all existing records) ----
    loans = (
        db.query(FundRequest)
        .filter(
            FundRequest.member_id == user.id,
            FundRequest.status.in_(
                (FundRequestStatus.disbursed, FundRequestStatus.repaying, FundRequestStatus.completed)
            ),
        )
        .order_by(FundRequest.disbursed_at.asc(), FundRequest.id.asc())
        .all()
    )
    all_reps = db.query(FundRepayment).filter(FundRepayment.member_id == user.id).all()
    reps_by_loan: dict[int, list] = {}
    for r in all_reps:
        reps_by_loan.setdefault(r.request_id, []).append(r)

    loan_rows = []
    overdue_total = 0
    outstanding_total = Decimal(0)
    for loan in loans:
        reps = reps_by_loan.get(loan.id, [])
        paid_principal = sum((_d(r.principal) for r in reps), Decimal(0))
        is_active = loan.status in (FundRequestStatus.disbursed, FundRequestStatus.repaying)
        outstanding = max(_d(loan.amount_approved) - paid_principal, Decimal(0)) if is_active else Decimal(0)
        outstanding_total += outstanding
        due_n, overdue_n, next_due = _loan_cycles(loan, reps, rate, now)
        overdue_total += overdue_n
        loan_rows.append({
            "request_id": loan.id,
            "amount": float(_d(loan.amount_approved)),
            "status": loan.status.value,
            "disbursed_at": loan.disbursed_at,
            "outstanding_principal": float(outstanding),
            "interest_cycles_due": due_n,
            "interest_cycles_overdue": overdue_n,
            "next_interest_due": next_due if is_active else None,
        })

    # ---- 1. repayment history ----
    on_time = sum(1 for r in all_reps if r.is_on_time)
    late = len(all_reps) - on_time
    evidence = len(all_reps) + overdue_total
    if evidence > 0:
        repayment = _factor(
            "repayment",
            score=on_time / evidence,
            reliable=evidence >= RELIABLE_REPAYMENT_EVIDENCE,
            detail=(
                f"{len(all_reps)} repayment(s) recorded ({on_time} on time, {late} late) and "
                f"{overdue_total} interest due date(s) passed unpaid."
            ),
        )
    elif not loans:
        repayment = _factor("repayment", score=None, detail="No loan taken yet, so there is no repayment history.")
    else:
        upcoming = [row["next_interest_due"] for row in loan_rows if row["next_interest_due"]]
        when = f" The first interest payment is due on {min(upcoming):%d %b %Y}." if upcoming else ""
        repayment = _factor(
            "repayment", score=None,
            detail="A loan is active but no payment has been due or recorded yet." + when,
        )

    # ---- 2. contribution consistency ----
    first_contrib = (
        db.query(func.min(Contribution.for_date))
        .filter(Contribution.member_id == user.id, Contribution.status == "Confirmed")
        .scalar()
    )
    if first_contrib is None:
        contributions = _factor("contributions", score=None, detail="No confirmed contribution yet.")
        eligible_days = 0
    else:
        first_day = max(first_contrib, cap_start)
        paid_days = {
            row[0]
            for row in db.query(Contribution.for_date)
            .filter(
                Contribution.member_id == user.id,
                Contribution.status == "Confirmed",
                Contribution.for_date >= first_day,
                Contribution.for_date <= today,
            )
            .distinct()
            .all()
        }
        # today is still in progress: an unpaid today is not a miss yet
        end_day = today if today in paid_days else today - timedelta(days=1)
        eligible_days = max((end_day - first_day).days + 1, 0)
        counted = sum(1 for d in paid_days if d <= end_day)
        if eligible_days < MIN_DAYS_FOR_CONSISTENCY:
            contributions = _factor(
                "contributions", score=None,
                detail=f"Only {eligible_days} day(s) observed so far; consistency needs at least "
                       f"{MIN_DAYS_FOR_CONSISTENCY} days.",
            )
        else:
            contributions = _factor(
                "contributions",
                score=_clamp01(counted / eligible_days),
                reliable=eligible_days >= RELIABLE_CONTRIBUTION_DAYS,
                detail=f"{counted} of {eligible_days} day(s) paid and confirmed since your first contribution.",
            )

    # ---- 3 + 4. balance snapshots (never in the future, never a missing one treated as zero) ----
    snap_filters = [MemberAvailableBalanceSnapshot.member_id == user.id]
    if BALANCE_SNAPSHOT_VALID_FROM is not None:
        snap_filters.append(MemberAvailableBalanceSnapshot.snapshot_day >= BALANCE_SNAPSHOT_VALID_FROM)
    balances = [
        float(_d(b))
        for _, b in db.query(MemberAvailableBalanceSnapshot.snapshot_day, MemberAvailableBalanceSnapshot.balance)
        .filter(
            *snap_filters,
            MemberAvailableBalanceSnapshot.snapshot_day >= cap_start,
            MemberAvailableBalanceSnapshot.snapshot_day <= today,
            MemberAvailableBalanceSnapshot.recorded_at <= now_aware,
        )
        .order_by(MemberAvailableBalanceSnapshot.snapshot_day.asc())
        .all()
    ]
    n = len(balances)
    average = sum(balances) / n if n else 0.0

    if n == 0:
        stability = _factor("stability", score=None, detail="No balance snapshot has been saved yet.")
        strength = _factor("strength", score=None, detail="No balance snapshot has been saved yet.")
    else:
        if n < 2:
            stability = _factor(
                "stability", score=None,
                detail="Only one day of balance is saved. One snapshot cannot show that a balance was "
                       "maintained, so stability needs snapshots from at least 2 days.",
            )
        else:
            stability = _factor(
                "stability",
                score=_clamp01(min(balances) / average) if average > 0 else 0.0,
                reliable=n >= RELIABLE_STABILITY_DAYS,
                detail=f"Lowest balance {_rupees(min(balances))} vs average {_rupees(average)} over {n} day(s).",
            )
        if not have_salary:
            strength = _factor("strength", score=None, detail="Your salary is not on file yet.")
        else:
            basis = "today's single snapshot" if n == 1 else f"{n} daily snapshots"
            strength = _factor(
                "strength",
                score=_clamp01(average / float(salary)),
                reliable=n >= RELIABLE_STRENGTH_DAYS,
                detail=f"Average balance {_rupees(average)} from {basis} vs monthly salary {_rupees(salary)}.",
            )

    # ---- 5. debt burden ----
    if not have_salary:
        debt = _factor("debt", score=None, detail="Your salary is not on file yet.")
    else:
        debt = _factor(
            "debt",
            score=1.0 - _clamp01(float(outstanding_total) / (float(salary) * DEBT_CAP_MONTHS)),
            reliable=True,
            detail=(
                f"{_rupees(outstanding_total)} principal outstanding on active loans."
                if outstanding_total > 0 else "No outstanding loan principal."
            ),
        )

    factors = [repayment, contributions, stability, strength, debt]

    # ---- combine ----
    calc = [f for f in factors if f["status"] == "calculated"]
    coverage = round(sum(WEIGHTS[f["key"]] for f in calc), 6)
    reliable_weight = round(sum(WEIGHTS[f["key"]] for f in calc if f["reliable"]), 6)

    missing = [f"{f['label']}: {f['detail']}" for f in factors if f["status"] == "insufficient"]

    first_dates = [d for d in (first_contrib,) if d]
    if balances:
        first_snap = db.query(func.min(MemberAvailableBalanceSnapshot.snapshot_day)).filter(*snap_filters).scalar()
        if first_snap:
            first_dates.append(first_snap)
    first_request = (
        db.query(func.min(FundRequest.requested_at)).filter(FundRequest.member_id == user.id).scalar()
    )
    if first_request:
        first_dates.append(first_request.date())
    first_activity = min(first_dates) if first_dates else None

    score = None
    category = None
    if coverage < MIN_COVERAGE_FOR_SCORE:
        status = "insufficient_data"
    else:
        weighted = sum(WEIGHTS[f["key"]] * f["raw"] for f in calc) / coverage
        score = max(SCORE_MIN, min(SCORE_MAX, SCORE_MIN + round((SCORE_MAX - SCORE_MIN) * weighted)))
        if reliable_weight >= RELIABLE_COVERAGE:
            status = "sufficient"
            category = score_category(score)
        else:
            status = "provisional"
            missing.extend(
                f"{f['label']}: based on limited history so far."
                for f in calc if not f["reliable"]
            )

    return {
        "score": score,
        "min_score": SCORE_MIN,
        "max_score": SCORE_MAX,
        "category": category,
        "status": status,
        "coverage_percent": round(coverage * 100),
        "first_activity_date": first_activity,
        "missing": missing,
        "calculated_at": now_aware,
        "factors": [{k: v for k, v in f.items() if k != "raw"} for f in factors],
        "loans": loan_rows,
    }