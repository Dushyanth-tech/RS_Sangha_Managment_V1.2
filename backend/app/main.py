from app.crypto import encrypt_value, decrypt_value, mask_last4, encrypt_bytes, decrypt_bytes, hash_value
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
# from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from app.credit_score import calculate_internal_score
from app.authSchema import CreditScoreResponse
from app.authSchema import NewUser, LoginUser, NewSanghas, Search, AdminRequestCreate,AddAdminRequest,RemoveSanghasPayload,SanghaUpdate, ProfileWizardUpdate, NotificationCreate, ClearNotificationsRequest, SanghaSavingsAccountCreate, CibilUpdate, FundRequestCreate, FundRequestReview, FundRepaymentCreate, FundPaymentCreate, FundPaymentConfirm, FundPaymentReject, ContributionCreate
from app.authSchema import (
    MemberBankBalanceSnapshotCreateResponse,
    MemberBankBalanceSnapshotResponse,
    MemberAvailableBalanceSnapshotCreateResponse,
    MemberAvailableBalanceSnapshotResponse,
    EmploymentProfileUpdate,
)
from app.bank_balance import (
    BankBalanceSourceUnavailable,
    fetch_verified_member_balance,
)
from decimal import Decimal
from app.authModal import (
    User, Sanghas, SubAdminRequest, RequestStatus, BankDetails, Notification,
    NotificationRecipient, SanghaSavingsAccount, Loan, LoanRepayment,
    LoanStatus, VerificationRequest,    FundRequest, FundRepayment, FundTransaction, FundRequestStatus,
    NotificationType, RecipientRule, NotificationStatus, FundPayment, Contribution,
    MemberBankBalanceSnapshot, MemberAvailableBalanceSnapshot,
)
from app.dbconnection import get_db, engine, Base
from app.auth import create_access_token, hash_password, verify_password, get_current_user
from sqlalchemy import or_,func, select
from sqlalchemy.orm import aliased, Session, joinedload
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from datetime import datetime, timezone, date, timedelta
from fastapi import Query
import re
import json
import os, uuid
import calendar

app = FastAPI()

origins = [
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_MEMBERS_PER_SANGHA = 20

UPLOAD_DIR = "uploads/profile_photos"
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024   # 5 MB per image


def _require_sangha_manager(db: Session, current_user_id, sangha_id: int) -> User:
    """Superadmin may manage any sangha; an admin only the sanghas where admin_id == self."""
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if user.role == "superadmin":
        return user
    if user.role == "admin":
        owns = db.query(Sanghas.id).filter(
            Sanghas.id == sangha_id, Sanghas.admin_id == user.id
        ).first()
        if owns:
            return user
        raise HTTPException(status_code=403, detail="You do not manage this Sangha.")
    raise HTTPException(status_code=403, detail="Only admin and superadmin can do this.")


def _looks_like_image(raw: bytes) -> bool:
    """Check the real file bytes (JPEG / PNG / WEBP), not the client-supplied content type."""
    return (
        raw[:3] == b"\xff\xd8\xff"
        or raw[:8] == b"\x89PNG\r\n\x1a\n"
        or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
    )


async def _read_image_limited(upload: UploadFile) -> bytes:
    raw = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image is too large (max 5 MB).")
    if not _looks_like_image(raw):
        raise HTTPException(status_code=400, detail="File is not a valid JPEG, PNG, or WEBP image.")
    return raw

@app.get("/overview")
def get_overview_stats(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user)
):
    current_user = db.query(User).filter(
        User.id == int(current_user_id)
    ).first()

    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="User not found."
        )

    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="Only superadmin can view overview stats."
        )

    total_admins = db.scalar(
        select(func.count(User.id)).where(
            User.role == "admin"
        )
    )

    total_sanghas = db.scalar(
        select(func.count(Sanghas.id))
    )

    total_members = db.query(User).filter(
        User.role == "member"
    ).count()

    # Verified members
    verified_members = db.query(User).filter(
        User.role == "member",
        User.isVerified == True
    ).count()

    # Unverified members
    unverified_members = db.query(User).filter(
        User.role == "member",
        User.isVerified == False
    ).count()

    pending_requests = db.scalar(
        select(func.count(SubAdminRequest.id)).where(
            SubAdminRequest.status == "pending"
        )
    )

    return {
        "totalAdmins": total_admins or 0,
        "totalSanghas": total_sanghas or 0,
        "pendingRequests": pending_requests or 0,
        "totalMembers": total_members or 0,
        "verifiedMembers": verified_members or 0,
        "unverifiedMembers": unverified_members or 0,
    }

@app.post("/auth/register")
def register_user(user: NewUser, db = Depends(get_db)):
    # Check if the email already exists in the database
    existing_user = db.query(User).filter(User.email == user.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    if db.query(User.id).filter(User.username == user.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(User.id).filter(User.phone == user.phone).first():
        raise HTTPException(status_code=400, detail="Phone number already registered")

    # Create a new user instance
    new_user = User(
        fullname=user.fullname,
        username=user.username,
        email=user.email,
        phone=user.phone,
        password=hash_password(user.password),  # Hash the password before storing it
    )

    # Add the new user to the database
    db.add(new_user)
    try:
        db.commit()
    except IntegrityError:           # FIX: race between check and insert
        db.rollback()
        raise HTTPException(status_code=400, detail="Email, username or phone already registered")
    db.refresh(new_user)

    return {"message": "User registered successfully", "user_id": new_user.id}

@app.post("/auth/login")
def login_user(
    user:LoginUser,
    db=Depends(get_db)
):
    db_user = db.query(User).filter(
        User.email == user.email
    ).first()

    if not db_user:
        raise HTTPException(
            status_code=400,
            detail="Invalid email or password"
        )

    if not verify_password(user.password, db_user.password):
        raise HTTPException(
            status_code=400,
            detail="Invalid email or password"
        )

    access_token = create_access_token({
        "sub": str(db_user.id),
        "email": db_user.email,
        "role": db_user.role
    })

    return {
        "message": "Login successful",
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": db_user.id,
            "fullname": db_user.fullname,
            "email": db_user.email,
            "role": db_user.role
        }
    }

@app.post("/sanghas")
def create_sangha(
    sangha: NewSanghas,
    db=Depends(get_db),
    current_user_id=Depends(get_current_user)
):
    current_user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role == "admin":
        admin_id = current_user.id            # self-assign, ignore payload
    elif current_user.role == "superadmin":
        admin_id = sangha.admin_id             # superadmin may leave unassigned or assign anyone
    else:
        raise HTTPException(status_code=403, detail="Only admin and superadmin can create a sangha.")

    new_sangha = Sanghas(
        name=sangha.name,
        address=sangha.address,
        city=sangha.city,
        state=sangha.state,
        isActive=True,
        membersCount=0,
        created_by=current_user.id,
        admin_id=admin_id,
        subadmin_id=None
    )
    db.add(new_sangha)
    db.commit()
    db.refresh(new_sangha)

    new_sangha.code = f"RS{new_sangha.id:05d}"
    db.commit()
    db.refresh(new_sangha)

    return new_sangha

@app.get("/sanghas")
def list_sanghas(db=Depends(get_db), current_user_id=Depends(get_current_user)):
    current_user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    admin = aliased(User)
    subadmin = aliased(User)

    query = (
        db.query(
            Sanghas,
            admin.fullname.label("admin_name"),
            subadmin.fullname.label("subadmin_name"),
        )
        .outerjoin(admin, Sanghas.admin_id == admin.id)
        .outerjoin(subadmin, Sanghas.subadmin_id == subadmin.id)
    )

    if current_user.role == "admin":
        query = query.filter(Sanghas.admin_id == current_user.id)
    # superadmin: no filter, sees all

    rows = query.all()

    return [
        {
            "id": s.id,
            "name": s.name,
            "code": s.code,
            "admin_id": s.admin_id,
            "admin_name": admin_name,
            "subadmin_id": s.subadmin_id,
            "subadmin_name": subadmin_name,
            "membersCount": s.membersCount,
        }
        for s, admin_name, subadmin_name in rows
    ]


@app.get("/member/my-sangha")
def get_my_sangha(
    db=Depends(get_db),
    current_user_id=Depends(get_current_user)
):
    current_user = db.query(User).filter(
        User.id == int(current_user_id)
    ).first()

    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="User not found."
        )

    if current_user.role != "member":
        raise HTTPException(
            status_code=403,
            detail="Only members can access this endpoint."
        )

    if current_user.sangha_id is None:
        return []

    admin = aliased(User)

    result = (
        db.query(
            Sanghas,
            admin.fullname.label("admin_name")
        )
        .outerjoin(admin, Sanghas.admin_id == admin.id)
        .filter(Sanghas.id == current_user.sangha_id)
        .first()
    )

    if not result:
        return []

    sangha, admin_name = result

    return [{
        "id": sangha.id,
        "code": sangha.code,
        "name": sangha.name,
        "address": sangha.address,
        "city": sangha.city,
        "state": sangha.state,
        "admin_name": admin_name,
        "membersCount": db.query(User).filter(
            User.sangha_id == sangha.id, User.role == "member"
        ).count(),
        "maxMembers": MAX_MEMBERS_PER_SANGHA,
    }]

@app.get("/member/my-sangha/members")
def get_my_sangha_members(
    db=Depends(get_db),
    current_user_id=Depends(get_current_user)
):
    current_user = db.query(User).filter(
        User.id == int(current_user_id)
    ).first()

    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="User not found."
        )

    if current_user.role != "member":
        raise HTTPException(
            status_code=403,
            detail="Only members can access this endpoint."
        )

    if current_user.sangha_id is None:
        return []

    members = (
        db.query(User)
        .filter(
            User.sangha_id == current_user.sangha_id,
            User.role == "member"
        )
        .order_by(User.fullname.asc())
        .all()
    )

    return [
        {
            "id": member.id,
            "name": member.fullname,
            "address": member.address,
            "is_current_user": member.id == current_user.id
        }
        for member in members
    ]


@app.post("/sanghas/{sangha_id}/members")
def add_member(
    sangha_id: int,
    payload: dict,  # {"member_id": int}
    db=Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    _require_sangha_manager(db, current_user_id, sangha_id)   # FIX: permission check
    member_id = payload.get("member_id")

    # Lock the sangha row so two simultaneous adds can't both slip past the limit
    sangha = (
        db.query(Sanghas)
        .filter(Sanghas.id == sangha_id)
        .with_for_update()
        .first()
    )
    if not sangha:
        raise HTTPException(404, "Sangha not found")

    member = db.query(User).filter(User.id == member_id).first()
    if not member:
        raise HTTPException(404, "User not found")

    if member.sangha_id is not None:
        raise HTTPException(
            400,
            "User already belongs to a sangha"
            if member.sangha_id != sangha_id
            else "User is already a member of this sangha"
        )

    # Count real rows rather than trusting membersCount, which can drift
    current_count = db.query(User).filter(User.sangha_id == sangha_id).count()
    if current_count >= MAX_MEMBERS_PER_SANGHA:
        raise HTTPException(
            400,
            f"This Sangha is full ({MAX_MEMBERS_PER_SANGHA} members maximum).",
        )

    member.sangha_id = sangha_id
    sangha.membersCount = current_count + 1
    db.commit()

    return {"detail": "Member added", "membersCount": sangha.membersCount}

@app.get("/users/search")
def search_members(
    q: str = "",
    role: str = "member",
    db=Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    current_user = (
        db.query(User)
        .filter(User.id == int(current_user_id))
        .first()
    )

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=403,
            detail="Only admin and superadmin can search users."
        )

    roles = [r.strip() for r in role.split(",") if r.strip()]

    query = db.query(User).filter(User.role.in_(roles))

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                User.fullname.ilike(like),
                User.email.ilike(like),
                User.phone.ilike(like),
            )
        )

    results = query.limit(20).all()

    sangha_ids = {u.sangha_id for u in results if u.sangha_id is not None}
    sangha_names = {}
    if sangha_ids:
        sangha_names = {
            s.id: s.name
            for s in db.query(Sanghas).filter(Sanghas.id.in_(sangha_ids)).all()
        }

    return [
        {
            "id": u.id,
            "name": u.fullname,
            "email": u.email,
            "phone": u.phone,
            "isActive": u.isActive,
            "role": u.role,
            "sanghaId": u.sangha_id,
            "sanghaName": sangha_names.get(u.sangha_id) if u.sangha_id else None,
        }
        for u in results
    ]

@app.get("/admins")
def list_admins(db=Depends(get_db), current_user_id=Depends(get_current_user)):
    rows = (
        db.query(
            User.id,
            User.fullname,
            User.email,
            User.isActive,
            func.count(Sanghas.id).label("sangha_count"),
        )
        .outerjoin(Sanghas, Sanghas.admin_id == User.id)
        .filter(User.role == "admin")
        .group_by(User.id)
        .all()
    )

    return [
        {
            "id": r.id,
            "name": r.fullname,
            "email": r.email,
            "sanghaCount": r.sangha_count,
            "status": "active" if r.isActive else "inactive",
        }
        for r in rows
    ]


@app.post("/admins")
def add_admin(
    payload: AddAdminRequest,
    db=Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    current_user = (
        db.query(User)
        .filter(User.id == int(current_user_id))
        .first()
    )

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="Only superadmin can assign admins."
        )

    # Find selected member/admin
    member = db.query(User).filter(
        User.id == payload.member_id
    ).first()

    if not member:
        raise HTTPException(status_code=404, detail="User not found")

    # User must be a member OR an existing admin (to allow multi-sangha admins)
    if member.role not in ("member", "admin"):
        raise HTTPException(
            status_code=400,
            detail="User is not eligible for promotion"
        )

    # Find selected Sangha
    sangha = db.query(Sanghas).filter(
        Sanghas.id == payload.sangha_id
    ).first()

    if not sangha:
        raise HTTPException(status_code=404, detail="Sangha not found")

    if sangha.admin_id is not None:
        raise HTTPException(
            status_code=400,
            detail="This Sangha already has an admin"
        )

    # --------------------------------
    # UPDATE USERS TABLE
    # --------------------------------

    member.role = "admin"
    # No member.sangha_id assignment — an admin's sanghas are derived from
    # Sanghas.admin_id (one-to-many), not stored on the User row.

    # --------------------------------
    # UPDATE SANGHAS TABLE
    # --------------------------------

    sangha.admin_id = member.id

    db.commit()
    db.refresh(member)
    db.refresh(sangha)

    return {
        "id": member.id,
        "name": member.fullname,
        "email": member.email,
        "role": member.role,
        "status": "active" if member.isActive else "inactive",

        "sanghaId": sangha.id,
        "sanghaName": sangha.name,
        "sanghaAdminId": sangha.admin_id,
    }

@app.delete("/admins/{admin_id}")
def remove_admin(
    admin_id: int,
    db=Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    admin = db.query(User).filter(User.id == admin_id, User.role == "admin").first()
    if not admin:
        raise HTTPException(404, "Admin not found")

    # Unassign this admin from every sangha they currently manage
    unassigned_count = (
        db.query(Sanghas)
        .filter(Sanghas.admin_id == admin_id)
        .update({Sanghas.admin_id: None})
    )

    admin.role = "member"
    db.commit()

    return {
        "detail": "Admin removed",
        "sanghas_unassigned": unassigned_count,
    }

@app.delete("/sanghas/{sangha_id}/members/{member_id}")
def remove_member(
    sangha_id: int,
    member_id: int,
    db=Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    _require_sangha_manager(db, current_user_id, sangha_id)   # FIX: permission check
    sangha = db.query(Sanghas).filter(Sanghas.id == sangha_id).first()
    if not sangha:
        raise HTTPException(404, "Sangha not found")

    member = db.query(User).filter(User.id == member_id).first()
    if not member:
        raise HTTPException(404, "User not found")

    if member.sangha_id != sangha_id:
        raise HTTPException(400, "User is not a member of this sangha")

    member.sangha_id = None
    if sangha.membersCount > 0:
        sangha.membersCount -= 1
    db.commit()

    return {"detail": "Member removed", "membersCount": sangha.membersCount}

@app.get("/admins/{admin_id}/sanghas")
def get_admin_sanghas(
    admin_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user)
):
    current_user = db.query(User).filter(User.id == int(current_user_id)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Only superadmin can view an admin's sanghas.")

    admin = db.query(User).filter(User.id == admin_id, User.role == "admin").first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    sanghas = db.query(Sanghas).filter(Sanghas.admin_id == admin_id).all()

    return [{"id": s.id, "name": s.name} for s in sanghas]


@app.delete("/admins/{admin_id}/sanghas")
def remove_admin_from_sanghas(
    admin_id: int,
    payload: RemoveSanghasPayload,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user)
):
    current_user = db.query(User).filter(User.id == int(current_user_id)).first()

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Only superadmin can remove an admin from sanghas.")

    admin = db.query(User).filter(User.id == admin_id, User.role == "admin").first()
    if not admin:
        raise HTTPException(status_code=404, detail="Admin not found")

    sanghas_to_update = db.query(Sanghas).filter(
        Sanghas.id.in_(payload.sangha_ids),
        Sanghas.admin_id == admin_id
    ).all()

    for sangha in sanghas_to_update:
        sangha.admin_id = None

    db.flush()  # make the unassignments visible to the count query below

    remaining_count = db.query(Sanghas).filter(Sanghas.admin_id == admin_id).count()

    demoted = False
    if remaining_count == 0:
        admin.role = "member"
        demoted = True

    db.commit()

    return {
        "detail": "Admin unassigned from selected sanghas",
        "sanghas_unassigned": len(sanghas_to_update),
        "demoted_to_member": demoted
    }

@app.get("/sanghas/{sangha_id}/members")
def list_sangha_members(
    sangha_id: int,
    q: str = "",
    db=Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    sangha = db.query(Sanghas).filter(Sanghas.id == sangha_id).first()
    if not sangha:
        raise HTTPException(404, "Sangha not found")

    query = db.query(User).filter(
        User.sangha_id == sangha_id,
        User.role == "member",
    )

    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                User.fullname.ilike(like),
                User.email.ilike(like),
                User.phone.ilike(like),
            )
        )

    members = query.all()

    return [
        {"id": m.id, "name": m.fullname, "email": m.email, "phone": m.phone}
        for m in members
    ]

@app.get("/admin/members")
def get_members_for_admin(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user)
):
    # Get actual logged-in user
    current_user = (
        db.query(User)
        .filter(User.id == int(current_user_id))
        .first()
    )

    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="User not found."
        )

    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=403,
            detail="Only admin and superadmin can access this."
        )

    members = (
        db.query(User)
        .filter(User.role == "member")
        .all()
    )

    return [
        {
            "id": member.id,
            "name": member.fullname,
            "email": member.email,
            "phone": member.phone,
            "address": member.address,
        }
        for member in members
    ]

@app.get("/sanghas/unassigned")
def get_unassigned_sanghas(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user)
):
    current_user = (
        db.query(User)
        .filter(User.id == int(current_user_id))
        .first()
    )

    if not current_user:
        raise HTTPException(
            status_code=401,
            detail="User not found."
        )

    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=403,
            detail="Only admin and superadmin can access this."
        )

    sanghas = (
        db.query(Sanghas)
        .filter(Sanghas.admin_id.is_(None))
        .all()
    )

    return [
        {
            "id": sangha.id,
            "name": sangha.name
        }
        for sangha in sanghas
    ]

@app.get("/sanghas/managed")
def get_managed_sanghas(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    current_user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin and superadmin can access this.")

    query = db.query(Sanghas).filter(Sanghas.subadmin_id.is_(None))

    if current_user.role == "admin":
        query = query.filter(Sanghas.admin_id == current_user.id)
    # superadmin: sees all sanghas without a subadmin yet

    sanghas = query.all()

    return [{"id": s.id, "name": s.name} for s in sanghas]

@app.post("/admin-requests")
def create_admin_request(
    data: AdminRequestCreate,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user)
):
    current_user = (
        db.query(User)
        .filter(User.id == int(current_user_id))
        .first()
    )

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=403,
            detail="Only admin and superadmin can create an admin request."
        )

    sangha = (
        db.query(Sanghas)
        .filter(Sanghas.id == data.sangha_id)
        .first()
    )

    if not sangha:
        raise HTTPException(status_code=404, detail="Sangha not found.")

    if sangha.admin_id is None:
        raise HTTPException(
            status_code=400,
            detail="This Sangha has no admin assigned yet."
        )

    if current_user.role == "admin" and sangha.admin_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only propose a subadmin for a Sangha you manage."
        )

    if sangha.subadmin_id is not None:
        raise HTTPException(
            status_code=400,
            detail="This Sangha already has a subadmin."
        )

    member = (
        db.query(User)
        .filter(User.id == data.requester_id)
        .first()
    )

    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")

    if member.role != "member":
        raise HTTPException(
            status_code=400,
            detail="Only members can be proposed as Admin."
        )

    if not data.message or not data.message.strip():
        raise HTTPException(status_code=400, detail="Reason is required.")

    existing_request = (
        db.query(SubAdminRequest)
        .filter(
            SubAdminRequest.sangha_id == data.sangha_id,
            SubAdminRequest.requester_id == data.requester_id,
            SubAdminRequest.status == RequestStatus.pending
        )
        .first()
    )

    if existing_request:
        raise HTTPException(status_code=400, detail="A pending request already exists.")

    new_request = SubAdminRequest(
    sangha_id=sangha.id,
    admin_id=current_user.id,
    requester_id=member.id,
    subadmin_name=member.fullname,
    subadmin_email=member.email,
    subadmin_phone=member.phone or "",
    address=member.address or "",
    aadhar_number=mask_last4(decrypt_value(member.id_proof_number_enc)) if member.id_proof_number_enc else "",   # FIX: masked, never plaintext
    message=data.message.strip(),
    experience=None,
    qualifications=None,
    availability=None,
    additional_info=None,
    status=RequestStatus.pending,
    rejection_reason=None,
    reviewed_at=None
    )

    db.add(new_request)
    db.commit()
    db.refresh(new_request)

    return {
        "message": "Admin request created successfully.",
        "request": {
            "id": new_request.id,
            "sangha_name": sangha.name,
            "candidate_name": member.fullname,
            "candidate_email": member.email,
            "candidate_phone": member.phone,
            "message": new_request.message,
            "status": new_request.status.value
        }
    }

@app.get("/admin-requests")
def get_admin_requests(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user)
):
    current_user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin and superadmin can view admin requests.")

    query = db.query(SubAdminRequest).order_by(SubAdminRequest.submitted_at.desc())

    if current_user.role == "admin":
        query = query.filter(SubAdminRequest.admin_id == current_user.id)
    # superadmin: sees all requests

    requests = query.all()

    result = []
    for request in requests:
        sangha = db.query(Sanghas).filter(Sanghas.id == request.sangha_id).first()
        requesting_admin = db.query(User).filter(User.id == request.admin_id).first()

        result.append({
            "id": request.id,
            "sangha_id": request.sangha_id,
            "sangha_name": sangha.name if sangha else "-",
            "candidate_name": request.subadmin_name,
            "candidate_email": request.subadmin_email,
            "candidate_phone": request.subadmin_phone,
            "requested_by": requesting_admin.fullname if requesting_admin else "-",
            "message": request.message,
            "status": request.status.value if hasattr(request.status, "value") else request.status,
            "rejection_reason": request.rejection_reason
        })

    return result

@app.patch("/admin-requests/{request_id}/approve")
def approve_admin_request(
    request_id: int,
    db=Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    current_user = (
        db.query(User)
        .filter(User.id == int(current_user_id))
        .first()
    )

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="Only superadmin can approve admin requests."
        )

    request_row = (
        db.query(SubAdminRequest)
        .filter(SubAdminRequest.id == request_id)
        .first()
    )

    if not request_row:
        raise HTTPException(status_code=404, detail="Request not found.")

    if request_row.status != RequestStatus.pending:
        raise HTTPException(status_code=400, detail="Request has already been reviewed.")

    sangha = (
        db.query(Sanghas)
        .filter(Sanghas.id == request_row.sangha_id)
        .first()
    )
    if not sangha:
        raise HTTPException(status_code=404, detail="Sangha no longer exists.")

    member = (
        db.query(User)
        .filter(User.id == request_row.requester_id)
        .first()
    )
    if not member:
        raise HTTPException(status_code=404, detail="Candidate member no longer exists.")

    if member.role != "member":
        raise HTTPException(status_code=400, detail="Candidate is no longer eligible for promotion.")

    outgoing_admin_id = sangha.admin_id

    # Promote the proposed member to admin, replacing the current one on this sangha
    member.role = "admin"
    sangha.admin_id = member.id

    # If the outgoing admin no longer manages any sangha, demote them back to member
    if outgoing_admin_id is not None and outgoing_admin_id != member.id:
        outgoing_admin = db.query(User).filter(User.id == outgoing_admin_id).first()
        if outgoing_admin:
            db.flush()  # make sangha.admin_id change visible to the count below
            remaining = db.query(Sanghas).filter(Sanghas.admin_id == outgoing_admin_id).count()
            if remaining == 0:
                outgoing_admin.role = "member"

    request_row.status = RequestStatus.approved
    request_row.reviewed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(request_row)

    return {
        "id": request_row.id,
        "status": request_row.status.value,
        "detail": "Request approved. Member promoted to admin of this Sangha."
    }

@app.patch("/admin-requests/{request_id}/reject")
def reject_admin_request(
    request_id: int,
    payload: dict,  # {"reason": str} — optional
    db=Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    current_user = (
        db.query(User)
        .filter(User.id == int(current_user_id))
        .first()
    )

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role != "superadmin":
        raise HTTPException(
            status_code=403,
            detail="Only superadmin can reject admin requests."
        )

    request_row = (
        db.query(SubAdminRequest)
        .filter(SubAdminRequest.id == request_id)
        .first()
    )

    if not request_row:
        raise HTTPException(status_code=404, detail="Request not found.")

    if request_row.status != RequestStatus.pending:
        raise HTTPException(status_code=400, detail="Request has already been reviewed.")

    request_row.status = RequestStatus.rejected
    request_row.rejection_reason = (payload or {}).get("reason")
    request_row.reviewed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(request_row)

    return {
        "id": request_row.id,
        "status": request_row.status.value,
        "rejection_reason": request_row.rejection_reason,
        "detail": "Request rejected."
    }

@app.get("/admin-requests/pending-count")
def get_pending_admin_requests_count(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user)
):
    current_user = (
        db.query(User)
        .filter(User.id == int(current_user_id))
        .first()
    )

    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=403,
            detail="Only admin and superadmin can view admin requests."
        )

    query = db.query(SubAdminRequest).filter(
        SubAdminRequest.status == RequestStatus.pending
    )

    if current_user.role == "admin":
        query = query.filter(SubAdminRequest.admin_id == current_user.id)
    # superadmin: no admin_id filter, sees global pending count

    count = query.count()

    return {"pending_count": count}

@app.patch("/sanghas/{sangha_id}")
def update_sangha(
    sangha_id: int,
    payload: SanghaUpdate,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    _require_sangha_manager(db, current_user_id, sangha_id)   # FIX: permission check
    sangha = db.query(Sanghas).filter(Sanghas.id == sangha_id).first()
    if not sangha:
        raise HTTPException(404, "Sangha not found")

    # Only touch fields that were actually sent and non-empty —
    # this is the safety net; the frontend also only sends changed fields.
    update_data = payload.dict(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None and value.strip() != "":
            setattr(sangha, field, value.strip())

    try:
        db.commit()
    except IntegrityError:           # FIX: duplicate sangha name -> 409 instead of 500
        db.rollback()
        raise HTTPException(409, "A Sangha with this name already exists.")
    db.refresh(sangha)

    return {
        "id": sangha.id,
        "name": sangha.name,
        "code": sangha.code,
        "address": sangha.address,
        "city": sangha.city,
        "state": sangha.state,
    }

@app.delete("/sanghas/{sangha_id}")
def delete_sangha(
    sangha_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    current_user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Not allowed.")

    sangha = db.query(Sanghas).filter(Sanghas.id == sangha_id).first()
    if not sangha:
        raise HTTPException(404, "Sangha not found")

    # An admin can only delete a sangha they manage
    if current_user.role == "admin" and sangha.admin_id != current_user.id:
        raise HTTPException(403, "You can only delete a Sangha you manage.")

    admin_id = sangha.admin_id
    subadmin_id = sangha.subadmin_id

    # 1. Detach all members (they become unassigned, not deleted)
    db.query(User).filter(User.sangha_id == sangha_id).update({User.sangha_id: None})

    # 2. Delete any requests tied to this sangha (they reference it by FK)
    db.query(SubAdminRequest).filter(SubAdminRequest.sangha_id == sangha_id).delete()

    # 3. Delete the sangha itself
    db.delete(sangha)
    db.flush()

    # 4. Demote the admin / subadmin if this was their only sangha
    demoted = []

    if admin_id:
        remaining = db.query(Sanghas).filter(Sanghas.admin_id == admin_id).count()
        if remaining == 0:
            admin_user = db.query(User).filter(User.id == admin_id).first()
            if admin_user and admin_user.role == "admin":
                admin_user.role = "member"
                demoted.append(admin_id)

    if subadmin_id:
        remaining = db.query(Sanghas).filter(Sanghas.subadmin_id == subadmin_id).count()
        if remaining == 0:
            sub_user = db.query(User).filter(User.id == subadmin_id).first()
            if sub_user and sub_user.role == "subadmin":
                sub_user.role = "member"
                demoted.append(subadmin_id)

    db.commit()

    return {"detail": "Sangha deleted", "demoted_user_ids": demoted}


@app.post("/me/photo")
async def upload_profile_photo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Only JPEG, PNG, or WEBP images are allowed.")

    user.profile_photo_image = await _read_image_limited(file)   # FIX: size + real-bytes check
    user.profile_photo_content_type = file.content_type
    db.commit()

    return {"detail": "Profile photo uploaded."}



@app.post(
    "/me/bank-balance/snapshots",
    response_model=MemberBankBalanceSnapshotCreateResponse,
)
def create_member_bank_balance_snapshot(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    """Record / refresh today's snapshot of the member's bank balance (users.bank_balance)."""
    user = _load_user(db, current_user_id)
    role = getattr(user.role, "value", user.role)
    if role != "member":
        raise HTTPException(
            status_code=403,
            detail="Only members can record their balance history.",
        )

    user = _lock_user(db, user.id)
    try:
        _, _, snapshot, created = _sync_balance_snapshots(db, user)
        db.commit()
        db.refresh(snapshot)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to save the balance snapshot.")
    return {"snapshot": snapshot, "created": created}


@app.get(
    "/me/bank-balance/history",
    response_model=list[MemberBankBalanceSnapshotResponse],
)
def get_member_bank_balance_history(
    days: int = Query(default=30, ge=1, le=3650),
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    """Return only the authenticated member's application balance history."""
    user = _load_user(db, current_user_id)

    role = getattr(user.role, "value", user.role)
    if role != "member":
        raise HTTPException(
            status_code=403,
            detail="Only members can view their available-balance history.",
        )

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    return (
        db.query(MemberBankBalanceSnapshot)
        .filter(
            MemberBankBalanceSnapshot.member_id == user.id,
            MemberBankBalanceSnapshot.recorded_at >= cutoff,
            MemberBankBalanceSnapshot.source == "RS-Sangha application",
        )
        .order_by(
            MemberBankBalanceSnapshot.recorded_at.asc(),
            MemberBankBalanceSnapshot.id.asc(),
        )
        .all()
    )



@app.post(
    "/me/available-balance/snapshots",
    response_model=MemberAvailableBalanceSnapshotCreateResponse,
)
def create_member_available_balance_snapshot(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    """Record / refresh today's snapshot of the member's bank balance (users.bank_balance).
    Called when the dashboard opens; the same row is also updated on every credit or debit."""
    user = _load_user(db, current_user_id)
    if user.role != "member":
        raise HTTPException(status_code=403, detail="Only members can record balance history.")

    user = _lock_user(db, user.id)
    try:
        snapshot, created, _, _ = _sync_balance_snapshots(db, user)
        db.commit()
        db.refresh(snapshot)
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to save the balance snapshot.")
    return {"snapshot": snapshot, "created": created}


@app.get(
    "/me/available-balance/history",
    response_model=list[MemberAvailableBalanceSnapshotResponse],
)
def get_member_available_balance_history(
    days: int = Query(default=30, ge=1, le=3650),
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = _load_user(db, current_user_id)
    if user.role != "member":
        raise HTTPException(status_code=403, detail="Only members can view available balance history.")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        return (
            db.query(MemberAvailableBalanceSnapshot)
            .filter(
                MemberAvailableBalanceSnapshot.member_id == user.id,
                MemberAvailableBalanceSnapshot.recorded_at >= cutoff,
            )
            .order_by(
                MemberAvailableBalanceSnapshot.recorded_at.asc(),
                MemberAvailableBalanceSnapshot.id.asc(),
            )
            .all()
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Unable to load available balance history.",
        ) from exc


@app.get("/me/profile-wizard")
def get_profile_wizard(db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    bank = db.query(BankDetails).filter(BankDetails.user_id == user.id).first()

    return {
        "profile": {
            "fullname": user.fullname,
            "date_of_birth": user.date_of_birth,
            "email": user.email,
            "phone": user.phone,
            "address": user.address,
            "id_proof_type": user.id_proof_type,
            "id_proof_number_masked": mask_last4(decrypt_value(user.id_proof_number_enc)) if user.id_proof_number_enc else None,
            "has_profile_photo": bool(user.profile_photo_image),
            "has_pan_image": bool(user.pan_image_enc),
            "has_id_proof_image": bool(user.id_proof_image_enc),
        },
        "banking": {
            "pan_number_masked": mask_last4(decrypt_value(user.pan_number_enc)) if user.pan_number_enc else None,
            "account_number_masked": mask_last4(decrypt_value(bank.account_number_enc)) if bank and bank.account_number_enc else None,
            "account_holder_name": bank.account_holder_name if bank else None,
            "bank_name": bank.bank_name if bank else None,
            "account_type": bank.account_type if bank else None,
            "ifsc_code": bank.ifsc_code if bank else None,
            "branch_name": bank.branch_name if bank else None,
        },
    }


@app.patch("/me/complete-profile")   # was @app.post(...)
async def complete_profile(
    fullname: str | None = Form(None),
    date_of_birth: str | None = Form(None),
    phone: str | None = Form(None),
    address: str | None = Form(None),
    id_proof_number: str | None = Form(None),
    id_proof_type: str | None = Form(None),
    id_proof_image: UploadFile | None = File(None),
    pan_number: str | None = Form(None),
    pan_image: UploadFile | None = File(None),
    account_number: str | None = Form(None),
    account_holder_name: str | None = Form(None),
    bank_name: str | None = Form(None),
    account_type: str | None = Form(None),
    ifsc_code: str | None = Form(None),
    branch_name: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    # ...body unchanged from what I gave you before...
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    if fullname:
        user.fullname = fullname.strip()
    if date_of_birth:
        user.date_of_birth = date_of_birth
    if phone:
        phone = phone.strip()
        if db.query(User.id).filter(User.phone == phone, User.id != user.id).first():
            raise HTTPException(422, detail="This phone number is already registered to another account.")
        user.phone = phone
    if address:
        user.address = address.strip()

    if id_proof_type:
        if id_proof_type not in ("aadhaar", "passport"):
            raise HTTPException(422, detail="id_proof_type must be 'aadhaar' or 'passport'.")
        user.id_proof_type = id_proof_type

    if id_proof_number:
        cleaned = id_proof_number.strip().upper()
        h = hash_value(cleaned)
        clash = db.query(User).filter(User.id_proof_number_hash == h, User.id != user.id).first()
        if clash:
            raise HTTPException(422, detail="This ID proof number is already registered to another account.")
        user.id_proof_number_enc = encrypt_value(cleaned)
        user.id_proof_number_hash = h

    if id_proof_image is not None:
        if id_proof_image.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(422, detail="ID proof image must be JPEG, PNG, or WEBP.")
        raw = await _read_image_limited(id_proof_image)
        user.id_proof_image_enc = encrypt_bytes(raw)
        user.id_proof_image_content_type = id_proof_image.content_type

    if pan_number:
        pan = pan_number.strip().upper()
        if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", pan):
            raise HTTPException(422, detail="Invalid PAN format.")
        h = hash_value(pan)
        clash = db.query(User).filter(User.pan_number_hash == h, User.id != user.id).first()
        if clash:
            raise HTTPException(422, detail="This PAN is already registered to another account.")
        user.pan_number_enc = encrypt_value(pan)
        user.pan_number_hash = h

    if pan_image is not None:
        if pan_image.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(422, detail="PAN image must be JPEG, PNG, or WEBP.")
        raw = await _read_image_limited(pan_image)
        user.pan_image_enc = encrypt_bytes(raw)
        user.pan_image_content_type = pan_image.content_type

    if any([account_number, account_holder_name, bank_name, account_type, ifsc_code, branch_name]):
        bank = db.query(BankDetails).filter(BankDetails.user_id == user.id).first()
        if not bank:
            bank = BankDetails(user_id=user.id)
            db.add(bank)

        if account_number:
            digits = re.sub(r"\D", "", account_number.strip())
            if not (9 <= len(digits) <= 18):
                raise HTTPException(422, detail="Account number length looks invalid.")
            bank.account_number_enc = encrypt_value(digits)
        if account_holder_name:
            bank.account_holder_name = account_holder_name.strip()
        if bank_name:
            bank.bank_name = bank_name.strip()
        if account_type:
            bank.account_type = account_type
        if ifsc_code:
            ifsc = ifsc_code.strip().upper()
            if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc):
                raise HTTPException(422, detail="Invalid IFSC code.")
            bank.ifsc_code = ifsc
        if branch_name:
            bank.branch_name = branch_name.strip()

    db.commit()
    return {"detail": "Profile updated successfully."}



def _require_superadmin(db: Session, current_user_id):
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Only superadmin can manage notifications.")
    return user


def _resolve_recipient_ids(db: Session, rule: str, sangha_ids: list[int] | None) -> list[int]:
    query = db.query(User.id).filter(User.role == "member")

    if sangha_ids:
        query = query.filter(User.sangha_id.in_(sangha_ids))
    else:
        query = query.filter(User.sangha_id.is_not(None))

    if rule == "Members Without Completed Profile":
        query = query.filter(
            or_(
                User.date_of_birth.is_(None),
                User.address.is_(None),
                User.id_proof_number_enc.is_(None),
            )
        )

    elif rule == "Members Without Banking Details":
        incomplete_banking_users = (
            db.query(BankDetails.user_id)
            .filter(
                or_(
                    BankDetails.account_holder_name.is_(None),
                    BankDetails.bank_name.is_(None),
                    BankDetails.account_type.is_(None),
                    BankDetails.ifsc_code.is_(None),
                    BankDetails.branch_name.is_(None),
                    BankDetails.account_number_enc.is_(None),
                )
            )
        )
        query = query.filter(
            or_(
                User.pan_number_enc.is_(None),
                ~User.id.in_(db.query(BankDetails.user_id)),
                User.id.in_(incomplete_banking_users),
            )
        )

    elif rule == "Members Without Completed Profile or Banking Details":
        incomplete_banking_users = (
            db.query(BankDetails.user_id)
            .filter(
                or_(
                    BankDetails.account_holder_name.is_(None),
                    BankDetails.bank_name.is_(None),
                    BankDetails.account_type.is_(None),
                    BankDetails.ifsc_code.is_(None),
                    BankDetails.branch_name.is_(None),
                    BankDetails.account_number_enc.is_(None),
                )
            )
        )
        query = query.filter(
            or_(
                User.date_of_birth.is_(None),
                User.address.is_(None),
                User.id_proof_number_enc.is_(None),
                User.pan_number_enc.is_(None),
                ~User.id.in_(db.query(BankDetails.user_id)),
                User.id.in_(incomplete_banking_users),
            )
        )

    return [row[0] for row in query.all()]


def _serialize(db: Session, n: Notification) -> dict:
    sangha_ids = json.loads(n.sangha_ids) if n.sangha_ids else []
    if sangha_ids:
        names = [s.name for s in db.query(Sanghas).filter(Sanghas.id.in_(sangha_ids)).all()]
        sangha_label = ", ".join(names) if names else "Selected Sanghas"
    else:
        sangha_label = "All Sanghas"

    return {
        "id": n.id,
        "title": n.title,
        "type": n.type,
        "recipient": n.recipient,
        "sanghaLabel": sangha_label,
        "sanghaIds": sangha_ids,
        "status": n.status,
        "sentAt": n.sent_at.strftime("%d %b %Y, %I:%M %p") if n.sent_at else "-",
        "message": n.message,
        "path": json.loads(n.navigation_path) if n.navigation_path else [],
    }

@app.get("/me/photo")
def get_my_photo(db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user or not user.profile_photo_image:
        raise HTTPException(404, "No profile photo on file.")
    return Response(content=user.profile_photo_image, media_type=user.profile_photo_content_type or "image/jpeg")


@app.get("/superadmin/members/{member_id}/photo")
def get_member_photo(member_id: int, db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    _require_superadmin(db, current_user_id)
    user = db.query(User).filter(User.id == member_id).first()
    if not user or not user.profile_photo_image:
        raise HTTPException(404, "No profile photo on file.")
    return Response(content=user.profile_photo_image, media_type=user.profile_photo_content_type or "image/jpeg")

@app.get("/me/pan-image")
def get_my_pan_image(db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user or not user.pan_image_enc:
        raise HTTPException(404, "No PAN image on file.")
    return Response(content=decrypt_bytes(user.pan_image_enc), media_type=user.pan_image_content_type or "image/jpeg")


@app.get("/me/id-proof-image")
def get_my_id_proof_image(db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user or not user.id_proof_image_enc:
        raise HTTPException(404, "No ID proof image on file.")
    return Response(content=decrypt_bytes(user.id_proof_image_enc), media_type=user.id_proof_image_content_type or "image/jpeg")


@app.get("/superadmin/members/{member_id}/pan-image")
def get_member_pan_image(member_id: int, db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    _require_superadmin(db, current_user_id)
    user = db.query(User).filter(User.id == member_id).first()
    if not user or not user.pan_image_enc:
        raise HTTPException(404, "No PAN image on file.")
    return Response(content=decrypt_bytes(user.pan_image_enc), media_type=user.pan_image_content_type or "image/jpeg")


@app.get("/superadmin/members/{member_id}/id-proof-image")
def get_member_id_proof_image(member_id: int, db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    _require_superadmin(db, current_user_id)
    user = db.query(User).filter(User.id == member_id).first()
    if not user or not user.id_proof_image_enc:
        raise HTTPException(404, "No ID proof image on file.")
    return Response(content=decrypt_bytes(user.id_proof_image_enc), media_type=user.id_proof_image_content_type or "image/jpeg")

@app.get("/notifications")
def list_notifications(db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    _require_superadmin(db, current_user_id)
    rows = db.query(Notification).order_by(Notification.created_at.desc()).all()
    return [_serialize(db, n) for n in rows]


@app.post("/notifications")
def create_notification(
    payload: NotificationCreate,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    admin = _require_superadmin(db, current_user_id)

    if not payload.title.strip() or not payload.message.strip():
        raise HTTPException(status_code=422, detail="Title and message are required.")

    notification = Notification(
        title=payload.title.strip(),
        type=payload.type,
        recipient=payload.recipient,
        sangha_ids=json.dumps(payload.sangha_ids) if payload.sangha_ids else None,
        message=payload.message.strip(),
        navigation_path=json.dumps(payload.navigation_path) if (payload.include_path and payload.navigation_path) else None,
        status="Sent" if payload.send_now else "Draft",
        created_by=admin.id,
        sent_at=datetime.now(timezone.utc) if payload.send_now else None,
    )
    db.add(notification)
    db.flush()

    if payload.send_now:
        for uid in _resolve_recipient_ids(db, payload.recipient, payload.sangha_ids):
            db.add(NotificationRecipient(notification_id=notification.id, user_id=uid))

    db.commit()
    db.refresh(notification)
    return _serialize(db, notification)


# ---------- Member-facing (for when the Member Notifications page connects) ----------

@app.get("/me/notifications")
def get_my_notifications(db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    rows = (
        db.query(NotificationRecipient, Notification)
        .join(Notification, NotificationRecipient.notification_id == Notification.id)
        .filter(NotificationRecipient.user_id == int(current_user_id))
        .order_by(Notification.sent_at.desc())
        .all()
    )
    return [
        {
            "id": recipient.id,
            "title": notif.title,
            "message": notif.message,
            "type": notif.type,
            "path": json.loads(notif.navigation_path) if notif.navigation_path else [],
            "sentAt": notif.sent_at.strftime("%d %b %Y, %I:%M %p") if notif.sent_at else "-",
            "isRead": recipient.is_read,
        }
        for recipient, notif in rows
    ]


@app.patch("/me/notifications/{recipient_id}/read")
def mark_notification_read(
    recipient_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    recipient = (
        db.query(NotificationRecipient)
        .filter(NotificationRecipient.id == recipient_id, NotificationRecipient.user_id == int(current_user_id))
        .first()
    )
    if not recipient:
        raise HTTPException(status_code=404, detail="Notification not found.")
    recipient.is_read = True
    recipient.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"detail": "Marked as read"}

@app.delete("/notifications/{notification_id}")
def delete_notification(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    _require_superadmin(db, current_user_id)

    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id)
        .first()
    )

    if not notification:
        raise HTTPException(
            status_code=404,
            detail="Notification not found."
        )

    # Delete related recipients first
    db.query(NotificationRecipient).filter(
        NotificationRecipient.notification_id == notification_id
    ).delete(synchronize_session=False)

    db.delete(notification)
    db.commit()

    return {"detail": "Notification deleted successfully."}


@app.post("/notifications/clear-selected")
def clear_selected_notifications(
    payload: ClearNotificationsRequest,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    _require_superadmin(db, current_user_id)

    if not payload.notification_ids:
        raise HTTPException(
            status_code=400,
            detail="No notifications selected."
        )

    db.query(NotificationRecipient).filter(
        NotificationRecipient.notification_id.in_(
            payload.notification_ids
        )
    ).delete(synchronize_session=False)

    deleted_count = (
        db.query(Notification)
        .filter(Notification.id.in_(payload.notification_ids))
        .delete(synchronize_session=False)
    )

    db.commit()

    return {
        "detail": "Selected notifications cleared successfully.",
        "deleted_count": deleted_count,
    }

def _require_staff(db: Session, current_user_id):
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if user.role != "superadmin" and user.role!="admin":
        raise HTTPException(status_code=403, detail="Only admin and superadmin can access this.")
    return user


@app.get("/superadmin/members")
def list_members(db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    _require_superadmin(db, current_user_id)

    sangha = aliased(Sanghas)
    admin = aliased(User)

    rows = (
        db.query(User, sangha.name, admin.fullname)
        .join(BankDetails, BankDetails.user_id == User.id)
        .outerjoin(sangha, User.sangha_id == sangha.id)
        .outerjoin(admin, sangha.admin_id == admin.id)
        .filter(
            User.role == "member",
            User.date_of_birth.is_not(None),
            User.address.is_not(None),
            User.id_proof_number_enc.is_not(None),
            User.pan_number_enc.is_not(None),
            BankDetails.account_number_enc.is_not(None),
        )
        .all()
    )

    return [
        {
            "id": u.id,
            "name": u.fullname,
            "email": u.email,
            "phone": u.phone,
            "sanghaName": sangha_name or "-",
            "adminName": admin_name or "-",
            "isVerified": u.isVerified,
        }
        for u, sangha_name, admin_name in rows
    ]

@app.get("/superadmin/members/{member_id}")
def get_member_detail(member_id: int, db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    _require_superadmin(db, current_user_id)

    member = db.query(User).filter(User.id == member_id, User.role == "member").first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")

    sangha_name = None
    if member.sangha_id:
        sangha = db.query(Sanghas).filter(Sanghas.id == member.sangha_id).first()
        sangha_name = sangha.name if sangha else None

    bank = db.query(BankDetails).filter(BankDetails.user_id == member.id).first()

    return {
        "id": member.id,
        "isVerified": member.isVerified,
        "profile": {
            "fullname": member.fullname,
            "email": member.email,
            "phone": member.phone,
            "address": member.address,
            "date_of_birth": member.date_of_birth,
            "id_proof_type": member.id_proof_type,
            "id_proof_number": decrypt_value(member.id_proof_number_enc) if member.id_proof_number_enc else None,
            "pan_number": decrypt_value(member.pan_number_enc) if member.pan_number_enc else None,
            "has_profile_photo": bool(member.profile_photo_image),
            "has_pan_image": bool(member.pan_image_enc),
            "has_id_proof_image": bool(member.id_proof_image_enc),
            "sanghaName": sangha_name or "-",
        },
        "banking": {
            "account_number": decrypt_value(bank.account_number_enc) if bank and bank.account_number_enc else None,
            "account_holder_name": bank.account_holder_name if bank else None,
            "bank_name": bank.bank_name if bank else None,
            "account_type": bank.account_type if bank else None,
            "ifsc_code": bank.ifsc_code if bank else None,
            "branch_name": bank.branch_name if bank else None,
        } if bank else None,
    }

@app.post("/superadmin/members/{member_id}/verify")
def verify_member(
    member_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    verifier = _require_staff(db, current_user_id)   # returns the logged-in user (admin or superadmin)

    member = db.query(User).filter(User.id == member_id, User.role == "member").first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")

    # Already verified: don't send a duplicate notification
    if member.isVerified:
        return {"detail": "Member already verified", "isVerified": True}

    member.isVerified = True

    db.query(VerificationRequest).filter(
        VerificationRequest.user_id == member.id,
        VerificationRequest.status == RequestStatus.pending,
    ).update({
        VerificationRequest.status: RequestStatus.approved,
        VerificationRequest.reviewed_by: verifier.id,
        VerificationRequest.reviewed_at: datetime.now(timezone.utc),
    })
    # ---------------------------------------------------------
    # NOTIFY THE MEMBER
    # ---------------------------------------------------------
    sangha = None
    if member.sangha_id:
        sangha = db.query(Sanghas).filter(Sanghas.id == member.sangha_id).first()

    greeting = (
        f"Dear {sangha.name} sangha member,"
        if sangha else "Dear member,"
    )
    verified_by = "Super Admin" if verifier.role == "superadmin" else "Admin"

    notification = Notification(
        title="Account details verified",
        type="Announcement",
        recipient="All Members",     # label only; delivery is via the NotificationRecipient row below
        sangha_ids=json.dumps([sangha.id]) if sangha else None,
        message=(
            f"{greeting}\n\n"
            f"Your account details have been verified successfully by the {verified_by}.\n\n"
            f"Your profile and banking details are now approved."
        ),
        navigation_path=None,
        status="Sent",
        created_by=verifier.id,
        sent_at=datetime.now(timezone.utc),
    )
    db.add(notification)
    db.flush()

    db.add(NotificationRecipient(notification_id=notification.id, user_id=member.id))

    db.commit()

    return {"detail": "Member verified", "isVerified": True}

@app.post("/sangha-savings-accounts")
def create_sangha_savings_account(
    payload: SanghaSavingsAccountCreate,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    current_user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role not in ("superadmin", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only admin and superadmin can create Sangha savings accounts."
        )

    sangha = db.query(Sanghas).filter(Sanghas.id == payload.sangha_id).first()
    if not sangha:
        raise HTTPException(status_code=404, detail="Sangha not found.")

    # An admin can only create an account for a Sangha they manage
    if current_user.role == "admin" and sangha.admin_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You can only create a savings account for a Sangha you manage."
        )

    existing_account = (
        db.query(SanghaSavingsAccount)
        .filter(SanghaSavingsAccount.sangha_id == sangha.id)
        .first()
    )
    if existing_account:
        raise HTTPException(
            status_code=409,
            detail="A savings account already exists for this Sangha."
        )

    cleaned_account_number = re.sub(r"\D", "", payload.account_number.strip())
    if not (9 <= len(cleaned_account_number) <= 18):
        raise HTTPException(
            status_code=422,
            detail="Account number must contain between 9 and 18 digits."
        )

    cleaned_ifsc = payload.ifsc.strip().upper()
    if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", cleaned_ifsc):
        raise HTTPException(status_code=422, detail="Invalid IFSC code.")

    cleaned_account_type = payload.account_type.strip().title()
    if cleaned_account_type not in ("Savings", "Current"):
        raise HTTPException(
            status_code=422,
            detail="Account type must be Savings or Current."
        )

    account_holder = payload.account_holder.strip()
    bank = payload.bank.strip()
    branch = payload.branch.strip()

    if not account_holder:
        raise HTTPException(status_code=422, detail="Account holder name is required.")
    if not bank:
        raise HTTPException(status_code=422, detail="Bank name is required.")
    if not branch:
        raise HTTPException(status_code=422, detail="Branch name is required.")

    savings_account = SanghaSavingsAccount(
        sangha_id=sangha.id,
        account_holder_enc=encrypt_value(account_holder),
        bank_name_enc=encrypt_value(bank),
        account_number_enc=encrypt_value(cleaned_account_number),
        ifsc_code_enc=encrypt_value(cleaned_ifsc),
        branch_name_enc=encrypt_value(branch),
        account_type_enc=encrypt_value(cleaned_account_type),
        balance_enc=encrypt_value("0"),   # always start at ₹0
        status="Active",
    )
    db.add(savings_account)
    db.flush()   # get the id, but don't commit yet

    # ---------------------------------------------------------
    # NOTIFY ALL MEMBERS OF THIS SANGHA
    # ---------------------------------------------------------
    member_ids = [
        row[0]
        for row in db.query(User.id)
        .filter(User.sangha_id == sangha.id, User.role == "member")
        .all()
    ]

    if member_ids:
        notification = Notification(
            title="Savings account created for your Sangha",
            type="Announcement",        # was "Info"
            recipient="All Members",    # was "Sangha Members"
            sangha_ids=json.dumps([sangha.id]),
            message=(
                f"Dear Sangha Members,\n\n" 
                f"A savings account has been created successfully for your Sangha "
                f"{sangha.name} ({sangha.code}).\n\n"
                f"Account Holder: {account_holder},\n"
                f"Bank: {bank},\n"
                f"Branch: {branch},\n"
                f"Account Type: {cleaned_account_type},\n"
                f"Account Number: {mask_last4(cleaned_account_number)},\n"
                f"IFSC: {cleaned_ifsc},\n"
                f"Opening Balance: ₹0"
            ),
            navigation_path=None,
            status="Sent",
            created_by=current_user.id,
            sent_at=datetime.now(timezone.utc),
        )
        db.add(notification)
        db.flush()

        for uid in member_ids:
            db.add(NotificationRecipient(notification_id=notification.id, user_id=uid))

    db.commit()
    db.refresh(savings_account)

    return {
        "message": "Sangha savings account created successfully.",
        "notified_members": len(member_ids),
        "account": {
            "id": savings_account.id,
            "sangha_id": sangha.id,
            "sangha_code": sangha.code,
            "sangha_name": sangha.name,
            "account_holder": account_holder,
            "bank": bank,
            "account_number": cleaned_account_number,
            "ifsc": cleaned_ifsc,
            "branch": branch,
            "account_type": cleaned_account_type,
            "balance": 0,
            "status": "Active",
        },
    }

@app.get("/sangha-savings-accounts")
def get_sangha_savings_accounts(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    current_user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role not in ("superadmin", "admin"):
        raise HTTPException(
            status_code=403,
            detail="Only admin and superadmin can view Sangha savings accounts."
        )

    accounts_query = (
        db.query(SanghaSavingsAccount)
        .options(joinedload(SanghaSavingsAccount.sangha))
        .join(Sanghas, Sanghas.id == SanghaSavingsAccount.sangha_id)
    )

    # An admin only sees accounts of Sanghas they manage
    if current_user.role == "admin":
        accounts_query = accounts_query.filter(Sanghas.admin_id == current_user.id)

    accounts = accounts_query.all()

    # Admin names in one query
    admin_ids = {a.sangha.admin_id for a in accounts if a.sangha.admin_id}
    admin_names = {}
    if admin_ids:
        admin_names = {
            u.id: u.fullname
            for u in db.query(User).filter(User.id.in_(admin_ids)).all()
        }

    # Member counts in one grouped query
    sangha_ids = [a.sangha_id for a in accounts]
    member_counts = {}
    if sangha_ids:
        member_counts = dict(
            db.query(User.sangha_id, func.count(User.id))
            .filter(User.sangha_id.in_(sangha_ids), User.role == "member")
            .group_by(User.sangha_id)
            .all()
        )

    def admin_label(sangha):
        if sangha.admin_id is None:
            return "—"
        if current_user.role == "admin" and sangha.admin_id == current_user.id:
            return "You"
        return admin_names.get(sangha.admin_id, "—")

    result = []
    for account in accounts:
        sangha = account.sangha

        result.append({
            "id": account.id,
            "status": account.status,
            "sanghaId": sangha.id,
            "sanghaCode": sangha.code,
            "sanghaName": sangha.name,
            "admin": admin_label(sangha),
            "membersCount": member_counts.get(sangha.id, 0),
            "bankDetails": {
                "accountHolder": decrypt_value(account.account_holder_enc),
                "bank": decrypt_value(account.bank_name_enc),
                "accountNumber": decrypt_value(account.account_number_enc),
                "ifsc": decrypt_value(account.ifsc_code_enc),
                "branch": decrypt_value(account.branch_name_enc),
                "accountType": decrypt_value(account.account_type_enc),
                "balance": float(decrypt_value(account.balance_enc)),
                "status": account.status,
            },
        })

    return result

@app.get("/sangha-savings-accounts/{sangha_id}/members")
def get_sangha_members(
    sangha_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    current_user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not current_user:
        raise HTTPException(status_code=401, detail="User not found.")

    if current_user.role not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Not allowed.")

    # Admins may only view Sanghas they manage
    if current_user.role == "admin":
        owns = db.query(Sanghas).filter(
            Sanghas.id == sangha_id,
            Sanghas.admin_id == current_user.id,
        ).first()
        if not owns:
            raise HTTPException(status_code=403, detail="You do not manage this Sangha.")

    rows = (
        db.query(User, BankDetails)
        .outerjoin(BankDetails, BankDetails.user_id == User.id)
        .filter(User.sangha_id == sangha_id, User.role == "member")
        .order_by(User.fullname.asc())
        .all()
    )

    return [
        {
            "id": member.id,
            "name": member.fullname,
            "bank": bank.bank_name if bank else None,
            "accountNumber": (
                mask_last4(decrypt_value(bank.account_number_enc))
                if bank and bank.account_number_enc else None
            ),
            "ifsc": bank.ifsc_code if bank else None,
            "status": "Verified" if member.isVerified else "Unverified",
        }
        for member, bank in rows
    ]

VERIFY_REQUEST_TITLE = "Account verification request"


def _is_profile_complete(user) -> bool:
    # Same fields your /superadmin/members list requires
    return all([user.date_of_birth, user.address, user.id_proof_number_enc, user.pan_number_enc])


def _is_banking_added(bank) -> bool:
    return bool(bank) and all([
        bank.account_holder_name, bank.bank_name, bank.account_type,
        bank.ifsc_code, bank.branch_name, bank.account_number_enc,
    ])


def _has_pending_verification_request(db: Session, user) -> bool:
    if user.isVerified:
        return False
    return (
        db.query(VerificationRequest.id)
        .filter(
            VerificationRequest.user_id == user.id,
            VerificationRequest.status == RequestStatus.pending,
        )
        .first()
        is not None
    )


@app.get("/me/account-status")
def get_account_status(db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    bank = db.query(BankDetails).filter(BankDetails.user_id == user.id).first()

    sangha_name = None
    if user.sangha_id:
        sangha = db.query(Sanghas).filter(Sanghas.id == user.sangha_id).first()
        sangha_name = sangha.name if sangha else None

    profile_complete = _is_profile_complete(user)
    banking_added = _is_banking_added(bank)

    return {
        "isActive": user.isActive is not False,
        "isVerified": bool(user.isVerified),
        "profileComplete": profile_complete,
        "bankingAdded": banking_added,
        "sanghaName": sangha_name,
        "verificationRequested": _has_pending_verification_request(db, user),
        "canRequestVerification": profile_complete and banking_added,
    }


@app.post("/me/verification-request")
def request_account_verification(db: Session = Depends(get_db), current_user_id=Depends(get_current_user)):
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    if user.role != "member":
        raise HTTPException(status_code=403, detail="Only members can request verification.")

    if user.isVerified:
        raise HTTPException(status_code=400, detail="Your account is already verified.")

    if _has_pending_verification_request(db, user):
        raise HTTPException(status_code=409, detail="A verification request is already pending.")

    bank = db.query(BankDetails).filter(BankDetails.user_id == user.id).first()
    if not (_is_profile_complete(user) and _is_banking_added(bank)):
        raise HTTPException(
            status_code=400,
            detail="Please complete your profile and banking details before requesting verification.",
        )

    sangha_name = None
    if user.sangha_id:
        sangha = db.query(Sanghas).filter(Sanghas.id == user.sangha_id).first()
        sangha_name = sangha.name if sangha else None

    db.add(VerificationRequest(user_id=user.id))
    notification = Notification(
        title=VERIFY_REQUEST_TITLE,
        type="Announcement",
        recipient="All Members",       # label only; delivery is via NotificationRecipient rows
        sangha_ids=json.dumps([user.sangha_id]) if user.sangha_id else None,
        message=(
            f"{user.fullname} ({sangha_name or 'No Sangha'}) has requested verification "
            f"of their account details.\n\n"
            f"Please review and verify them from Manage Members."
        ),
        navigation_path=None,
        status="Sent",
        created_by=user.id,
        sent_at=datetime.now(timezone.utc),
    )
    db.add(notification)
    db.flush()

    superadmin_ids = [row[0] for row in db.query(User.id).filter(User.role == "superadmin").all()]
    for uid in superadmin_ids:
        db.add(NotificationRecipient(notification_id=notification.id, user_id=uid))

    db.commit()

    return {"detail": "Verification request sent.", "verificationRequested": True}

@app.get("/member/home-summary")
def get_member_home_summary(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if user.role != "member":
        raise HTTPException(status_code=403, detail="Only members can access this endpoint.")

    # Sangha savings balance (belongs to the Sangha, not the member)
    savings = None
    if user.sangha_id:
        account = (
            db.query(SanghaSavingsAccount)
            .filter(SanghaSavingsAccount.sangha_id == user.sangha_id)
            .first()
        )
        if account:
            savings = {
                "balance": float(decrypt_value(account.balance_enc)),
                "status": account.status,
            }

    # Not in your models yet: these stay None / 0 until you add the columns
    # (or replace with a query on your future loans table).
    cibil_score = getattr(user, "cibil_score", None)
    outstanding_debt = getattr(user, "outstanding_debt", None) or 0

    debts = _member_debts(db, user.id)
    return {
        "savings": savings,
        "cibilScore": user.cibil_score,
        "outstandingDebt": float(sum((d["outstanding"] for d in debts), ZERO)),
        "interestDue": float(sum((d["interest"] for d in debts), ZERO)),
        "interestRate": float(INTEREST_RATE_PERCENT),
    }

@app.get("/me/credit-score", response_model=CreditScoreResponse)
def get_my_credit_score(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    """RS-Sangha INTERNAL score for the logged-in member only. The member is taken from the JWT;
    the request carries no member id, so nobody can ask for someone else's score."""
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    if user.role != "member":
        raise HTTPException(status_code=403, detail="Only members have an RS-Sangha score.")
    try:
        return calculate_internal_score(db, user)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="Unable to calculate your RS-Sangha score right now.") from exc


@app.patch("/superadmin/members/{member_id}/cibil")
def set_member_cibil(
    member_id: int,
    payload: CibilUpdate,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    _require_staff(db, current_user_id)

    member = db.query(User).filter(User.id == member_id, User.role == "member").first()
    if not member:
        raise HTTPException(status_code=404, detail="Member not found.")

    member.cibil_score = payload.score
    member.cibil_updated_at = datetime.now(timezone.utc)
    db.commit()

    return {"detail": "CIBIL score updated", "cibilScore": member.cibil_score}

# =====================================================================
# SANGHA SAVINGS: member emergency money requests
# =====================================================================

ACTIVE_STATUSES = (FundRequestStatus.disbursed, FundRequestStatus.repaying)
OPEN_STATUSES = (
    FundRequestStatus.pending,
    FundRequestStatus.under_review,
    FundRequestStatus.approved,
)
ZERO = Decimal(0)


def _d(value) -> Decimal:
    return Decimal(str(value if value is not None else 0))


def _member_available_balance(requests) -> Decimal:
    try:
        active = (request for request in requests if request.status in ACTIVE_STATUSES)
        balance = sum((_d(request.amount_approved) for request in active), ZERO)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise ValueError("Could not calculate the available balance.") from exc
    if (
        not balance.is_finite()
        or balance.as_tuple().exponent < -2
        or abs(balance) >= Decimal("10000000000000000")
    ):
        raise ValueError("Calculated available balance is outside the supported money range.")
    return balance


BALANCE_SNAPSHOT_SOURCE = "RS-Sangha application"


def _lock_user(db: Session, member_id: int) -> User:
    """Load the member's row and lock it until commit, so balance changes cannot overlap."""
    user = (
        db.query(User).filter(User.id == member_id)
        .with_for_update().populate_existing().first()
    )
    if not user:
        raise HTTPException(status_code=404, detail="Member not found.")
    return user


def _sync_balance_snapshots(db: Session, user: User):
    """Write the member's CURRENT users.bank_balance into today's snapshot rows.
    One row per member per day (IST) in both snapshot tables; the row is UPDATED every time the
    balance changes, so the day always shows the latest balance. Caller commits."""
    now = datetime.now(timezone.utc)
    day = _today_ist()
    balance = _d(user.bank_balance)

    avail = (
        db.query(MemberAvailableBalanceSnapshot)
        .filter(
            MemberAvailableBalanceSnapshot.member_id == user.id,
            MemberAvailableBalanceSnapshot.snapshot_day == day,
        )
        .first()
    )
    avail_new = avail is None
    if avail_new:
        avail = MemberAvailableBalanceSnapshot(
            member_id=user.id, balance=balance, recorded_at=now, snapshot_day=day,
        )
        db.add(avail)
    else:
        avail.balance = balance
        avail.recorded_at = now

    reference = f"application-available-balance:{day.isoformat()}"
    bank = (
        db.query(MemberBankBalanceSnapshot)
        .filter(
            MemberBankBalanceSnapshot.member_id == user.id,
            MemberBankBalanceSnapshot.source == BALANCE_SNAPSHOT_SOURCE,
            MemberBankBalanceSnapshot.source_reference == reference,
        )
        .first()
    )
    bank_new = bank is None
    if bank_new:
        bank = MemberBankBalanceSnapshot(
            member_id=user.id, balance=balance, recorded_at=now,
            source=BALANCE_SNAPSHOT_SOURCE, source_reference=reference,
        )
        db.add(bank)
    else:
        bank.balance = balance
        bank.recorded_at = now

    db.flush()
    return avail, avail_new, bank, bank_new


def _apply_balance_change(db: Session, member_id: int, delta: Decimal) -> User:
    """Credit (+) or debit (-) users.bank_balance and refresh today's snapshot in the same
    transaction. Refuses to take the balance below zero. Caller commits."""
    user = _lock_user(db, member_id)
    new_balance = _d(user.bank_balance) + _d(delta)
    if new_balance < 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient bank balance. The member has {_d(user.bank_balance):,.2f} "
                f"but {abs(_d(delta)):,.2f} must be debited."
            ),
        )
    user.bank_balance = new_balance
    _sync_balance_snapshots(db, user)
    return user


def _spendable_balance(db: Session, user: User) -> Decimal:
    """users.bank_balance minus money already promised in payments still waiting for admin confirmation."""
    pending_contrib = (
        db.query(func.coalesce(func.sum(Contribution.amount), 0))
        .filter(Contribution.member_id == user.id, Contribution.status == "Pending")
        .scalar()
    )
    pending_pay = (
        db.query(func.coalesce(func.sum(FundPayment.amount), 0))
        .filter(FundPayment.member_id == user.id, FundPayment.status == "Pending")
        .scalar()
    )
    return _d(user.bank_balance) - _d(pending_contrib) - _d(pending_pay)


def _require_balance(db: Session, user: User, amount: Decimal, what: str) -> None:
    """Block any payment larger than the member's bank balance. Locks the user row so two
    simultaneous requests cannot both spend the same balance."""
    db.query(User).filter(User.id == user.id).with_for_update().populate_existing().first()
    spendable = _spendable_balance(db, user)
    if spendable < _d(amount):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient bank balance. You can pay up to {max(spendable, ZERO):,.2f} right now, "
                f"but this {what} is {_d(amount):,.2f}."
            ),
        )


def _load_user(db: Session, current_user_id) -> User:
    user = db.query(User).filter(User.id == int(current_user_id)).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    return user


def _month_start() -> datetime:
    return datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _account_for(db: Session, sangha_id: int, lock: bool = False):
    q = db.query(SanghaSavingsAccount).filter(SanghaSavingsAccount.sangha_id == sangha_id)
    if lock:
        q = q.with_for_update()
    return q.first()


def _balance(account) -> Decimal:
    return _d(decrypt_value(account.balance_enc))


def _store_balance(account, value: Decimal) -> None:
    account.balance_enc = encrypt_value(f"{value:.2f}")


def _scoped_sangha(db: Session, user: User, sangha_id: int | None):
    """The Sangha this caller is allowed to see. The backend, not the client, decides."""
    if user.role == "member":
        if not user.sangha_id:
            return None
        return db.query(Sanghas).filter(Sanghas.id == user.sangha_id).first()

    if user.role in ("admin", "superadmin"):
        q = db.query(Sanghas)
        if user.role == "admin":
            q = q.filter(Sanghas.admin_id == user.id)
        if sangha_id is not None:
            sangha = q.filter(Sanghas.id == sangha_id).first()
            if not sangha:
                raise HTTPException(status_code=403, detail="You do not manage this Sangha.")
            return sangha
        return q.order_by(Sanghas.id).first()

    raise HTTPException(status_code=403, detail="Not allowed.")


def _repaid_map(db: Session, request_ids: list[int]) -> dict:
    if not request_ids:
        return {}
    rows = (
        db.query(FundRepayment.request_id, func.coalesce(func.sum(FundRepayment.principal), 0))
        .filter(FundRepayment.request_id.in_(request_ids))
        .group_by(FundRepayment.request_id)
        .all()
    )
    return {rid: _d(total) for rid, total in rows}


def _outstanding_of(req: FundRequest, repaid_map: dict) -> Decimal:
    if req.status not in ACTIVE_STATUSES:
        return ZERO
    return max(_d(req.amount_approved) - repaid_map.get(req.id, ZERO), ZERO)


def _member_outstanding(db: Session, member_id: int) -> Decimal:
    reqs = (
        db.query(FundRequest)
        .filter(FundRequest.member_id == member_id, FundRequest.status.in_(ACTIVE_STATUSES))
        .all()
    )
    rm = _repaid_map(db, [r.id for r in reqs])
    return sum((_outstanding_of(r, rm) for r in reqs), ZERO)


def _verification_label(db: Session, user: User) -> str:
    if user.isActive is False:
        return "Restricted"
    if user.isVerified:
        return "Verified"
    return "Pending Verification" if _has_pending_verification_request(db, user) else "Not Verified"


def _trust(db: Session, member_id: int) -> dict:
    reqs = (
        db.query(FundRequest)
        .filter(FundRequest.member_id == member_id)
        .order_by(FundRequest.requested_at.desc(), FundRequest.id.desc())
        .all()
    )
    reps = db.query(FundRepayment).filter(FundRepayment.member_id == member_id).all()
    on_time = sum(1 for r in reps if r.is_on_time)
    return {
        "monthlySalary": float(reqs[0].monthly_salary) if reqs else None,
        "previousRequests": len(reqs),
        "completedRequests": sum(1 for r in reqs if r.status == FundRequestStatus.completed),
        # Share of repayments the admin marked on-time. Sangha history only, NOT a credit score.
        "repaymentConsistency": round(on_time * 100 / len(reps), 1) if reps else None,
        "currentOutstanding": float(_member_outstanding(db, member_id)),
        "lastRepayment": max(r.paid_at for r in reps).isoformat() if reps else None,
    }


def _blockers(db: Session, user: User, sangha, account, balance) -> list[dict]:
    out = []

    def add(code, message):
        out.append({"code": code, "message": message})

    if user.isActive is False:
        add("restricted", "Your account currently has restricted access.")
    if not user.isVerified:
        add("not_verified", "Your account must be verified before requesting emergency money.")
    if not sangha:
        add("no_sangha", "You are not currently assigned to a Sangha.")
    elif not account or account.status != "Active":
        add("no_account", "No active Sangha Savings Account is available.")
    elif balance is None or balance <= 0:
        add("no_funds", "Insufficient Sangha Savings balance for this request.")
    if not (user.fullname and user.phone and user.address):
        add("profile_incomplete", "Please add your phone number and address in your profile first.")
    if (
        db.query(FundRequest.id)
        .filter(FundRequest.member_id == user.id, FundRequest.status.in_(OPEN_STATUSES))
        .first()
    ):
        add("open_request", "You already have a request in progress.")
    return out


def _fund_block(db: Session, sangha_id: int, balance: Decimal) -> dict:
    month_start = _month_start()
    total_sum = lambda col: func.coalesce(func.sum(col), 0)  # noqa: E731

    disbursed = (
        db.query(total_sum(FundRequest.amount_approved))
        .filter(FundRequest.sangha_id == sangha_id, FundRequest.status.in_(ACTIVE_STATUSES))
        .scalar()
    )
    repaid = (
        db.query(total_sum(FundRepayment.principal))
        .join(FundRequest, FundRequest.id == FundRepayment.request_id)
        .filter(FundRequest.sangha_id == sangha_id, FundRequest.status.in_(ACTIVE_STATUSES))
        .scalar()
    )
    with_members = max(_d(disbursed) - _d(repaid), ZERO)
    total = balance + with_members

    monthly_given = (
        db.query(total_sum(FundRequest.amount_approved))
        .filter(FundRequest.sangha_id == sangha_id, FundRequest.disbursed_at >= month_start)
        .scalar()
    )
    monthly_returned = (
        db.query(total_sum(FundRepayment.principal + FundRepayment.interest))
        .filter(FundRepayment.sangha_id == sangha_id, FundRepayment.paid_at >= month_start)
        .scalar()
    )
    interest_returned = (
        db.query(total_sum(FundRepayment.interest))
        .filter(FundRepayment.sangha_id == sangha_id)
        .scalar()
    )
    pending = (
        db.query(func.count(FundRequest.id))
        .filter(
            FundRequest.sangha_id == sangha_id,
            FundRequest.status.in_((FundRequestStatus.pending, FundRequestStatus.under_review)),
        )
        .scalar()
    )
    active_accounts = (
        db.query(func.count(func.distinct(FundRequest.member_id)))
        .filter(FundRequest.sangha_id == sangha_id, FundRequest.status.in_(ACTIVE_STATUSES))
        .scalar()
    )

    return {
        "balance": float(balance),
        "withMembers": float(with_members),
        "total": float(total),
        "utilization": round(float(with_members * 100 / total), 1) if total > 0 else 0,
        "pendingRequests": pending or 0,
        "monthlyGiven": float(_d(monthly_given)),
        "monthlyReturned": float(_d(monthly_returned)),
        "interestReturned": float(_d(interest_returned)),
        "activeAccounts": active_accounts or 0,
    }


def _notify_user(db: Session, sender_id: int, user_id: int, title: str, message: str, sangha_id=None):
    n = Notification(
        title=title,
        type=NotificationType.announcement,
        recipient=RecipientRule.all_members,   # label only; delivery is the recipient row below
        sangha_ids=json.dumps([sangha_id]) if sangha_id else None,
        message=message,
        navigation_path=None,
        status=NotificationStatus.sent,
        created_by=sender_id,
        sent_at=datetime.now(timezone.utc),
    )
    db.add(n)
    db.flush()
    db.add(NotificationRecipient(notification_id=n.id, user_id=user_id))


def _staff_request(db: Session, current_user_id, request_id: int, lock: bool = False):
    user = _load_user(db, current_user_id)
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin and superadmin can do this.")

    q = db.query(FundRequest).filter(FundRequest.id == request_id)
    if lock:
        q = q.with_for_update()
    req = q.first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found.")

    sangha = db.query(Sanghas).filter(Sanghas.id == req.sangha_id).first()
    if user.role == "admin" and (not sangha or sangha.admin_id != user.id):
        raise HTTPException(status_code=403, detail="You do not manage this Sangha.")
    if req.member_id == user.id:
        raise HTTPException(status_code=403, detail="You cannot act on your own request.")
    return user, req, sangha


# ---------------------------------------------------------------------
# GET /sangha-savings/overview
# ---------------------------------------------------------------------
@app.get("/sangha-savings/overview")
def get_savings_overview(
    sangha_id: int | None = None,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = _load_user(db, current_user_id)
    role = getattr(user.role, "value", user.role)
    sangha = _scoped_sangha(db, user, sangha_id)
    account = _account_for(db, sangha.id) if sangha else None
    balance = _balance(account) if account else None

    result = {
        "role": role,
        "sangha": {"id": sangha.id, "name": sangha.name, "code": sangha.code} if sangha else None,
        "account": None,
        "fund": None,
    }

    if account:
        result["account"] = {
            "bank": decrypt_value(account.bank_name_enc),
            "accountHolder": decrypt_value(account.account_holder_enc),
            "accountNumberMasked": mask_last4(decrypt_value(account.account_number_enc)),
            "ifsc": decrypt_value(account.ifsc_code_enc),
            "branch": decrypt_value(account.branch_name_enc),
            "accountType": decrypt_value(account.account_type_enc),
            "status": account.status,
        }
        if role == "member":
            result["fund"] = {"balance": float(balance)}      # members never see fund internals
        else:
            result["fund"] = _fund_block(db, sangha.id, balance)

    if role == "member":
        reqs = db.query(FundRequest).filter(FundRequest.member_id == user.id).all()
        rm = _repaid_map(db, [r.id for r in reqs])
        active = [r for r in reqs if r.status in ACTIVE_STATUSES]
        received_statuses = ACTIVE_STATUSES + (FundRequestStatus.completed,)
        reps = db.query(FundRepayment).filter(FundRepayment.member_id == user.id).all()
        month_start = _month_start()

        debts = _member_debts(db, user.id)
        pending_payments = (
            db.query(FundPayment)
            .filter(FundPayment.member_id == user.id, FundPayment.status == "Pending")
            .all()
        )

        result["member"] = {
            "verificationStatus": _verification_label(db, user),
            "bankBalance": float(_d(user.bank_balance)),   # users.bank_balance
            # ASSUMPTION: money credited to the member from requests still being repaid.
            "availableBalance": float(_member_available_balance(reqs)),
            "outstanding": float(sum((_outstanding_of(r, rm) for r in active), ZERO)),
            "totalReceived": float(sum((_d(r.amount_approved) for r in reqs if r.status in received_statuses), ZERO)),
            "totalRepaid": float(sum((_d(p.principal) + _d(p.interest) for p in reps), ZERO)),
            "totalInterestPaid": float(sum((_d(p.interest) for p in reps), ZERO)),
            "receivedThisMonth": float(sum(
                (_d(r.amount_approved) for r in reqs if r.disbursed_at and r.disbursed_at >= month_start), ZERO
            )),
            "profile": {"fullname": user.fullname, "phone": user.phone, "address": user.address},
            "trust": _trust(db, user.id),
            # ---- interest + payments ----
            "interestRate": float(INTEREST_RATE_PERCENT),
            "interestDue": float(sum((d["interest"] for d in debts), ZERO)),
            "debts": [
                {
                    "id": d["req"].id,
                    "approvedAmount": float(d["req"].amount_approved or 0),
                    "outstanding": float(d["outstanding"]),
                    "interest": float(d["interest"]),
                    "monthlyInterest": float(
                        (d["outstanding"] * INTEREST_RATE_PERCENT / 100).quantize(Decimal("0.01"))
                    ),
                    "disbursedAt": d["req"].disbursed_at.isoformat() if d["req"].disbursed_at else None,
                }
                for d in debts
            ],
            "pendingPayments": [
                {"id": p.id, "kind": p.kind, "amount": float(p.amount),
                 "reference": p.reference, "createdAt": p.created_at.isoformat()}
                for p in pending_payments
            ],
        }
        blockers = _blockers(db, user, sangha, account, balance)
        result["eligibility"] = {"canRequest": not blockers, "reasons": blockers}

    return result

# ---------------------------------------------------------------------
# GET /sangha-savings/history
# Member: own records.  Admin/superadmin: the selected Sangha's records.
# ---------------------------------------------------------------------
TXN_LABELS = {
    "disbursement": "Emergency Fund Received",
    "repayment": "Repayment (returned to Sangha)",
    "interest": "Interest Paid",
}


@app.get("/sangha-savings/history")
def get_savings_history(
    sangha_id: int | None = None,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = _load_user(db, current_user_id)
    is_member = user.role == "member"
    sangha = None if is_member else _scoped_sangha(db, user, sangha_id)
    if not is_member and not sangha:
        return {"requests": [], "repayments": [], "transactions": [], "payments": []}

    def scope(model):
        return model.member_id == user.id if is_member else model.sangha_id == sangha.id

    reqs = (
        db.query(FundRequest).filter(scope(FundRequest))
        .order_by(FundRequest.requested_at.desc(), FundRequest.id.desc()).limit(100).all()
    )
    reps = (
        db.query(FundRepayment).filter(scope(FundRepayment))
        .order_by(FundRepayment.paid_at.asc(), FundRepayment.id.asc()).all()
    )
    txns = (
        db.query(FundTransaction).filter(scope(FundTransaction))
        .order_by(FundTransaction.created_at.desc(), FundTransaction.id.desc()).limit(100).all()
    )
    pays = (
        db.query(FundPayment)
        .filter(scope(FundPayment), FundPayment.status.in_(("Pending", "Rejected")))
        .order_by(FundPayment.created_at.desc()).limit(50).all()
    )

    req_by_id = {}
    if reps:
        req_by_id = {
            r.id: r for r in db.query(FundRequest).filter(FundRequest.id.in_({p.request_id for p in reps})).all()
        }

    user_ids = (
        {r.member_id for r in reqs}
        | {r.reviewed_by for r in reqs if r.reviewed_by}
        | {p.member_id for p in reps}
        | {t.member_id for t in txns}
        | {p.member_id for p in pays}
    )
    names = {}
    if user_ids:
        names = dict(db.query(User.id, User.fullname).filter(User.id.in_(user_ids)).all())

    rm = _repaid_map(db, [r.id for r in reqs])

    requests_out = [
        {
            "id": r.id,
            "memberName": names.get(r.member_id),
            "amount": float(r.amount_requested),
            "approvedAmount": float(r.amount_approved) if r.amount_approved is not None else None,
            "outstanding": float(_outstanding_of(r, rm)),
            "reason": r.reason,
            "status": r.status.value,
            "requestedAt": r.requested_at.isoformat() if r.requested_at else None,
            "reviewer": names.get(r.reviewed_by) if r.reviewed_by else None,
            "rejectionReason": r.rejection_reason,
        }
        for r in reqs
    ]

    cumulative, repayments_out = {}, []
    for p in reps:
        cumulative[p.request_id] = cumulative.get(p.request_id, ZERO) + _d(p.principal)
        base = _d(req_by_id[p.request_id].amount_approved)
        repayments_out.append({
            "id": p.id,
            "requestId": p.request_id,
            "memberName": names.get(p.member_id),
            "paidAt": p.paid_at.isoformat(),
            "amount": float(_d(p.principal) + _d(p.interest)),
            "principal": float(p.principal),
            "interest": float(p.interest),
            "remaining": float(max(base - cumulative[p.request_id], ZERO)),
            "status": "Completed",
        })
    repayments_out.reverse()

    transactions_out = [
        {
            "id": t.id,
            "memberName": names.get(t.member_id),
            "date": t.created_at.isoformat(),
            "type": TXN_LABELS.get(t.kind, t.kind),
            "amount": float(t.amount),
            "direction": "Received" if t.kind == "disbursement" else "Paid",
            "status": "Completed",
        }
        for t in txns
    ]

    return {
        "requests": requests_out,
        "repayments": repayments_out[:100],
        "transactions": transactions_out,
        "payments": [
            {
                "id": p.id,
                "requestId": p.request_id,
                "memberName": names.get(p.member_id),
                "kind": p.kind,
                "amount": float(p.amount),
                "reference": p.reference,
                "status": p.status,
                "createdAt": p.created_at.isoformat(),
                "rejectionReason": p.rejection_reason,
            }
            for p in pays
        ],
    }


# ---------------------------------------------------------------------
# POST /sangha-savings/requests   (member only)
# ---------------------------------------------------------------------
@app.post("/sangha-savings/requests")
def create_fund_request(
    payload: FundRequestCreate,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = _load_user(db, current_user_id)
    if user.role != "member":
        raise HTTPException(status_code=403, detail="Only members can request emergency money.")

    sangha = db.query(Sanghas).filter(Sanghas.id == user.sangha_id).first() if user.sangha_id else None
    # Locking the account row serialises simultaneous submissions for this Sangha
    account = _account_for(db, sangha.id, lock=True) if sangha else None
    balance = _balance(account) if account else None

    blockers = _blockers(db, user, sangha, account, balance)
    if blockers:
        raise HTTPException(status_code=409, detail=blockers[0]["message"])

    if payload.amount > balance:
        raise HTTPException(status_code=422, detail="Requested amount exceeds the available Sangha Savings balance.")

    req = FundRequest(
        member_id=user.id,
        sangha_id=sangha.id,
        amount_requested=payload.amount,
        monthly_salary=payload.monthly_salary,
        reason=payload.reason.strip(),
        status=FundRequestStatus.pending,
    )
    db.add(req)
    db.flush()

    if sangha.admin_id:
        _notify_user(
            db, user.id, sangha.admin_id,
            "New emergency money request",
            f"{user.fullname} has requested ₹{payload.amount:,.2f} from {sangha.name}. Please review it in Sangha Savings.",
            sangha.id,
        )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="You already have a request in progress.")

    db.refresh(req)
    return {
        "message": "Request submitted successfully.",
        "request": {
            "id": req.id,
            "amount": float(req.amount_requested),
            "status": req.status.value,
            "requestedAt": req.requested_at.isoformat(),
        },
    }




# ---------------------------------------------------------------------
# GET /sangha-savings/requests/{id}   (admin / superadmin review detail)
# ---------------------------------------------------------------------

def _month_shift(first_of_month: date, k: int) -> date:
    total = first_of_month.year * 12 + (first_of_month.month - 1) + k
    return date(total // 12, total % 12 + 1, 1)


def _member_contribution_summary(db: Session, member_id: int) -> dict:
    """What this member has contributed to the Sangha: all-time totals plus the last 6 months."""
    today = _today_ist()
    cur = today.replace(day=1)

    first_date = (
        db.query(func.min(Contribution.for_date))
        .filter(Contribution.member_id == member_id, Contribution.status == "Confirmed")
        .scalar()
    )
    # Months before the first contribution are not counted as missed
    start = cur if not first_date else max(_month_shift(cur, -5), first_date.replace(day=1))

    totals = (
        db.query(func.coalesce(func.sum(Contribution.amount), 0), func.count(Contribution.id))
        .filter(Contribution.member_id == member_id, Contribution.status == "Confirmed")
        .one()
    )
    waiting_amount = (
        db.query(func.coalesce(func.sum(Contribution.amount), 0))
        .filter(Contribution.member_id == member_id, Contribution.status == "Pending")
        .scalar()
    )

    rows = (
        db.query(Contribution)
        .filter(
            Contribution.member_id == member_id,
            Contribution.status.in_(("Pending", "Confirmed")),
            Contribution.for_date >= start,
        )
        .all()
    )
    paid, waiting, amount = {}, {}, {}
    for r in rows:
        key = (r.for_date.year, r.for_date.month)
        if r.status == "Confirmed":
            paid[key] = paid.get(key, 0) + 1
            amount[key] = amount.get(key, ZERO) + _d(r.amount)
        else:
            waiting[key] = waiting.get(key, 0) + 1

    months = []
    m = start
    while m <= cur:
        key = (m.year, m.month)
        last = date(m.year, m.month, calendar.monthrange(m.year, m.month)[1])
        lo = max(m, first_date) if first_date else m
        hi = min(last, today)
        expected = max((hi - lo).days + 1, 0)
        paid_days, waiting_days = paid.get(key, 0), waiting.get(key, 0)
        months.append({
            "month": m.strftime("%B %Y"),
            "expectedDays": expected,
            "paidDays": paid_days,
            "waitingDays": waiting_days,
            "missedDays": max(expected - paid_days - waiting_days, 0),
            "paidAmount": float(amount.get(key, ZERO)),
        })
        m = _month_shift(m, 1)
    months.reverse()   # newest first

    return {
        "dailyAmount": float(CONTRIBUTION_PER_DAY),
        "totalPaid": float(_d(totals[0])),
        "daysPaid": int(totals[1]),
        "since": first_date.isoformat() if first_date else None,
        "waitingAmount": float(_d(waiting_amount)),
        "months": months,
    }

@app.get("/sangha-savings/requests/{request_id}")
def get_fund_request_detail(
    request_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    _, req, sangha = _staff_request(db, current_user_id, request_id)
    member = db.query(User).filter(User.id == req.member_id).first()
    account = _account_for(db, req.sangha_id)
    trust = _trust(db, req.member_id)

    all_reps = (
        db.query(FundRepayment)
        .filter(FundRepayment.member_id == req.member_id)
        .order_by(FundRepayment.paid_at.desc())
        .all()
    )
    debts = _member_debts(db, req.member_id)
    rm = _repaid_map(db, [req.id])

    borrowed = (
        db.query(func.coalesce(func.sum(FundRequest.amount_approved), 0))
        .filter(
            FundRequest.member_id == req.member_id,
            FundRequest.status.in_(ACTIVE_STATUSES + (FundRequestStatus.completed,)),
        )
        .scalar()
    )

    return {
        "id": req.id,
        "status": req.status.value,
        "memberName": member.fullname,
        "phone": member.phone,
        "sangha": {"id": sangha.id, "name": sangha.name, "code": sangha.code},
        "amount": float(req.amount_requested),
        "approvedAmount": float(req.amount_approved) if req.amount_approved is not None else None,
        "monthlySalary": float(req.monthly_salary),
        "reason": req.reason,
        "requestedAt": req.requested_at.isoformat(),
        "rejectionReason": req.rejection_reason,
        "availableFund": float(_balance(account)) if account else None,
        "verification": _verification_label(db, member),
        "previousRequests": max(trust["previousRequests"] - 1, 0),
        "completedRequests": trust["completedRequests"],
        "currentOutstanding": trust["currentOutstanding"],
        "repaymentConsistency": trust["repaymentConsistency"],
        "requestOutstanding": float(_outstanding_of(req, rm)),
        # ---- debt ----
        "totalBorrowed": float(_d(borrowed)),
        "totalRepaidPrincipal": float(sum((_d(p.principal) for p in all_reps), ZERO)),
        "interestDueNow": float(sum((x["interest"] for x in debts), ZERO)),
        "interestRate": float(INTEREST_RATE_PERCENT),
        "activeDebts": [
            {
                "id": x["req"].id,
                "approvedAmount": float(x["req"].amount_approved or 0),
                "outstanding": float(x["outstanding"]),
                "interest": float(x["interest"]),
                "disbursedAt": x["req"].disbursed_at.isoformat() if x["req"].disbursed_at else None,
            }
            for x in debts
        ],
        # ---- interest / repayment history ----
        "totalInterestPaid": float(sum((_d(p.interest) for p in all_reps), ZERO)),
        "totalRepayments": len(all_reps),
        "onTimeRepayments": sum(1 for p in all_reps if p.is_on_time),
        "repayments": [
            {"paidAt": p.paid_at.isoformat(), "principal": float(p.principal),
             "interest": float(p.interest), "isOnTime": p.is_on_time}
            for p in all_reps[:10]
        ],
        # ---- Sangha contributions ----
        "contributions": _member_contribution_summary(db, req.member_id),
    }

# ---------------------------------------------------------------------
# PATCH /sangha-savings/requests/{id}/review
# ---------------------------------------------------------------------
@app.patch("/sangha-savings/requests/{request_id}/review")
def review_fund_request(
    request_id: int,
    payload: FundRequestReview,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user, req, sangha = _staff_request(db, current_user_id, request_id, lock=True)
    decidable = (FundRequestStatus.pending, FundRequestStatus.under_review)

    if payload.action == "start_review":
        if req.status != FundRequestStatus.pending:
            raise HTTPException(status_code=400, detail="Only a pending request can be moved to review.")
        req.status = FundRequestStatus.under_review

    elif payload.action == "approve":
        if req.status not in decidable:
            raise HTTPException(status_code=400, detail="This request has already been decided.")

        member = db.query(User).filter(User.id == req.member_id).first()
        if not member or not member.isVerified:
            raise HTTPException(status_code=400, detail="The member's account must be verified first.")

        amount = payload.approved_amount or _d(req.amount_requested)
        if amount > _d(req.amount_requested):
            raise HTTPException(status_code=422, detail="Approved amount cannot exceed the requested amount.")

        # Lock the Sangha account so two approvals can't spend the same money
        account = _account_for(db, req.sangha_id, lock=True)
        if not account or account.status != "Active":
            raise HTTPException(status_code=400, detail="No active Sangha Savings Account is available.")

        balance = _balance(account)
        if balance < amount:
            raise HTTPException(status_code=400, detail="Insufficient Sangha Savings balance for this amount.")

        # Approve AND credit in one transaction
        _store_balance(account, balance - amount)
        _apply_balance_change(db, req.member_id, amount)     # credit the member
        req.amount_approved = amount
        req.status = FundRequestStatus.disbursed
        req.disbursed_at = datetime.utcnow()

        db.add(FundTransaction(
            sangha_id=req.sangha_id, member_id=req.member_id, request_id=req.id,
            kind="disbursement", amount=amount, created_by=user.id,
        ))

        _notify_user(
            db, user.id, req.member_id, "Fund Request Approved",
            f"Your request for ₹{req.amount_requested:,.2f} has been approved and "
            f"₹{amount:,.2f} has been credited to you from Sangha Savings.\n\n"
            f"Approved Amount: ₹{amount:,.2f}\n"
            f"Status: Approved & Credited",
            req.sangha_id,
        )

    else:  # reject
        if req.status not in decidable:
            raise HTTPException(status_code=400, detail="This request has already been decided.")
        reason = (payload.reason or "").strip()
        if not reason:
            raise HTTPException(status_code=422, detail="Please give a reason for rejecting this request.")
        req.status = FundRequestStatus.rejected
        req.rejection_reason = reason
                # reject branch
        _notify_user(
            db, user.id, req.member_id, "Fund Request Rejected",
            f"Your request for ₹{req.amount_requested:,.2f} was rejected.\n\n"
            f"Reason: {reason}\n"
            f"Status: Rejected",
            req.sangha_id,
        )

    req.reviewed_by = user.id
    req.reviewed_at = datetime.utcnow()
    db.commit()
    return {"detail": "Request updated.", "status": req.status.value}


# ---------------------------------------------------------------------
# POST /sangha-savings/requests/{id}/disburse
# Records that approved money was handed to the member and takes it out of the fund.
# ---------------------------------------------------------------------
@app.post("/sangha-savings/requests/{request_id}/disburse")
def disburse_fund_request(
    request_id: int,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user, req, _ = _staff_request(db, current_user_id, request_id, lock=True)
    if req.status != FundRequestStatus.approved:
        raise HTTPException(status_code=400, detail="Only an approved request can be disbursed.")

    account = _account_for(db, req.sangha_id, lock=True)
    if not account or account.status != "Active":
        raise HTTPException(status_code=400, detail="No active Sangha Savings Account is available.")

    amount = _d(req.amount_approved)
    balance = _balance(account)
    if balance < amount:
        raise HTTPException(status_code=400, detail="Insufficient Sangha Savings balance.")

    _store_balance(account, balance - amount)
    _apply_balance_change(db, req.member_id, amount)         # credit the member
    req.status = FundRequestStatus.disbursed
    req.disbursed_at = datetime.utcnow()
    db.add(FundTransaction(
        sangha_id=req.sangha_id, member_id=req.member_id, request_id=req.id,
        kind="disbursement", amount=amount, created_by=user.id,
    ))
    _notify_user(
        db, user.id, req.member_id, "Emergency money disbursed",
        f"₹{amount:,.2f} has been credited to you from Sangha Savings.", req.sangha_id,
    )
    db.commit()
    return {"detail": "Disbursed.", "status": req.status.value}


# ---------------------------------------------------------------------
# POST /sangha-savings/requests/{id}/repayments
# Principal + interest go back into the Sangha fund. Interest is typed in, never calculated.
# ---------------------------------------------------------------------
@app.post("/sangha-savings/requests/{request_id}/repayments")
def record_fund_repayment(
    request_id: int,
    payload: FundRepaymentCreate,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user, req, _ = _staff_request(db, current_user_id, request_id, lock=True)
    if req.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail="Repayments can only be recorded for disbursed requests.")

    principal, interest = _d(payload.principal), _d(payload.interest)
    if principal + interest <= 0:
        raise HTTPException(status_code=422, detail="Enter a repayment amount greater than ₹0.")

    outstanding = _outstanding_of(req, _repaid_map(db, [req.id]))
    if principal > outstanding:
        raise HTTPException(status_code=422, detail=f"Principal exceeds the outstanding amount (₹{outstanding:,.2f}).")

    account = _account_for(db, req.sangha_id, lock=True)
    if not account:
        raise HTTPException(status_code=400, detail="No Sangha Savings Account found.")

    _store_balance(account, _balance(account) + principal + interest)
    _apply_balance_change(db, req.member_id, -(principal + interest))   # debit the member

    db.add(FundRepayment(
        request_id=req.id, sangha_id=req.sangha_id, member_id=req.member_id,
        principal=principal, interest=interest, is_on_time=payload.is_on_time, recorded_by=user.id,
    ))
    if principal > 0:
        db.add(FundTransaction(sangha_id=req.sangha_id, member_id=req.member_id, request_id=req.id,
                               kind="repayment", amount=principal, created_by=user.id))
    if interest > 0:
        db.add(FundTransaction(sangha_id=req.sangha_id, member_id=req.member_id, request_id=req.id,
                               kind="interest", amount=interest, created_by=user.id))

    remaining = outstanding - principal
    if remaining <= 0:
        req.status = FundRequestStatus.completed
        req.completed_at = datetime.utcnow()
    else:
        req.status = FundRequestStatus.repaying

    _notify_user(
        db, user.id, req.member_id, "Repayment recorded",
        f"A repayment of ₹{principal + interest:,.2f} was recorded. Remaining: ₹{remaining:,.2f}.",
        req.sangha_id,
    )
    db.commit()
    return {"detail": "Repayment recorded.", "status": req.status.value, "remaining": float(remaining)}

def _inbox_query(db: Session, user: User):
    """Requests this admin/superadmin may act on. Never includes the caller's own requests."""
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin and superadmin can view requests.")

    q = (
        db.query(FundRequest, Sanghas, User)
        .join(Sanghas, Sanghas.id == FundRequest.sangha_id)
        .join(User, User.id == FundRequest.member_id)
        .filter(FundRequest.member_id != user.id)
    )
    if user.role == "admin":
        q = q.filter(Sanghas.admin_id == user.id)   # only Sanghas they manage
    return q

@app.get("/sangha-savings/inbox/count")
def get_request_inbox_count(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    """Bell badge: pending fund requests + payments + contributions waiting for the admin."""
    user = _load_user(db, current_user_id)

    requests_waiting = _inbox_query(db, user).filter(FundRequest.status == FundRequestStatus.pending).count()
    payments_waiting = _payments_query(db, user).filter(FundPayment.status == "Pending").count()
    contribution_batches = {
        c.batch_id
        for c, _, _ in _contributions_query(db, user).filter(Contribution.status == "Pending").all()
    }
    return {"count": requests_waiting + payments_waiting + len(contribution_batches)}


@app.get("/sangha-savings/inbox")
def get_request_inbox(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = _load_user(db, current_user_id)
    rows = (
        _inbox_query(db, user)
        .order_by(FundRequest.requested_at.desc(), FundRequest.id.desc())
        .limit(200)
        .all()
    )

    reviewer_ids = {r.reviewed_by for r, _, _ in rows if r.reviewed_by}
    reviewers = {}
    if reviewer_ids:
        reviewers = dict(db.query(User.id, User.fullname).filter(User.id.in_(reviewer_ids)).all())

    iso = lambda v: v.isoformat() if v else None  # noqa: E731

    pending_count = (
        _inbox_query(db, user).filter(FundRequest.status == FundRequestStatus.pending).count()
    )

    return {
        "pendingCount": pending_count,
        "items": [
            {
                "id": r.id,
                "memberId": r.member_id,
                "memberName": member.fullname,
                "memberVerified": bool(member.isVerified),
                "sanghaId": sangha.id,
                "sanghaName": sangha.name,
                "sanghaCode": sangha.code,
                "amount": float(r.amount_requested),
                "approvedAmount": float(r.amount_approved) if r.amount_approved is not None else None,
                "monthlySalary": float(r.monthly_salary),
                "reason": r.reason,
                "status": r.status.value,
                "requestedAt": iso(r.requested_at),
                "reviewedBy": reviewers.get(r.reviewed_by),
                "reviewedAt": iso(r.reviewed_at),
                "rejectionReason": r.rejection_reason,
                "disbursedAt": iso(r.disbursed_at),
                "completedAt": iso(r.completed_at),
            }
            for r, sangha, member in rows
        ],
    }

# =====================================================================
# INTEREST + MEMBER PAYMENTS
# =====================================================================

INTEREST_RATE_PERCENT = Decimal("10")   # per month, on the outstanding principal


def _interest_due_for(db: Session, req: FundRequest, outstanding: Decimal) -> Decimal:
    """INTEREST_RATE_PERCENT of the outstanding principal, minus interest already paid this month."""
    monthly = (outstanding * INTEREST_RATE_PERCENT / 100).quantize(Decimal("0.01"))
    paid = (
        db.query(func.coalesce(func.sum(FundRepayment.interest), 0))
        .filter(FundRepayment.request_id == req.id, FundRepayment.paid_at >= _month_start())
        .scalar()
    )
    return max(monthly - _d(paid), ZERO)


def _member_debts(db: Session, member_id: int) -> list[dict]:
    """Every request the member still owes on, oldest first, with principal and interest due."""
    reqs = (
        db.query(FundRequest)
        .filter(FundRequest.member_id == member_id, FundRequest.status.in_(ACTIVE_STATUSES))
        .order_by(FundRequest.disbursed_at.asc(), FundRequest.id.asc())
        .all()
    )
    rm = _repaid_map(db, [r.id for r in reqs])
    debts = []
    for r in reqs:
        outstanding = _outstanding_of(r, rm)
        if outstanding > 0:
            debts.append({
                "req": r,
                "outstanding": outstanding,
                "interest": _interest_due_for(db, r, outstanding),
            })
    return debts


def _apply_repayment(db: Session, user: User, req: FundRequest, principal: Decimal,
                     interest: Decimal, is_on_time: bool) -> dict:
    """Records a repayment and returns the money to the Sangha fund. Caller commits."""
    if req.status not in ACTIVE_STATUSES:
        raise HTTPException(status_code=400, detail="Repayments can only be recorded for disbursed requests.")
    if principal + interest <= 0:
        raise HTTPException(status_code=422, detail="Enter a repayment amount greater than ₹0.")

    outstanding = _outstanding_of(req, _repaid_map(db, [req.id]))
    if principal > outstanding:
        raise HTTPException(status_code=422, detail=f"Principal exceeds the outstanding amount (₹{outstanding:,.2f}).")

    account = _account_for(db, req.sangha_id, lock=True)
    if not account:
        raise HTTPException(status_code=400, detail="No Sangha Savings Account found.")

    _store_balance(account, _balance(account) + principal + interest)

    db.add(FundRepayment(
        request_id=req.id, sangha_id=req.sangha_id, member_id=req.member_id,
        principal=principal, interest=interest, is_on_time=is_on_time, recorded_by=user.id,
    ))
    if principal > 0:
        db.add(FundTransaction(sangha_id=req.sangha_id, member_id=req.member_id, request_id=req.id,
                               kind="repayment", amount=principal, created_by=user.id))
    if interest > 0:
        db.add(FundTransaction(sangha_id=req.sangha_id, member_id=req.member_id, request_id=req.id,
                               kind="interest", amount=interest, created_by=user.id))

    remaining = outstanding - principal
    if remaining <= 0:
        req.status = FundRequestStatus.completed
        req.completed_at = datetime.utcnow()
    else:
        req.status = FundRequestStatus.repaying

    _notify_user(
        db, user.id, req.member_id, "Payment confirmed",
        f"Your payment of ₹{principal + interest:,.2f} has been received and recorded. "
        f"Remaining principal: ₹{remaining:,.2f}.",
        req.sangha_id,
    )
    return {"status": req.status.value, "remaining": float(remaining)}


def _payments_query(db: Session, user: User):
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin and superadmin can view payments.")
    q = (
        db.query(FundPayment, Sanghas, User)
        .join(Sanghas, Sanghas.id == FundPayment.sangha_id)
        .join(User, User.id == FundPayment.member_id)
        .filter(FundPayment.member_id != user.id)
    )
    if user.role == "admin":
        q = q.filter(Sanghas.admin_id == user.id)
    return q


def _staff_payment(db: Session, current_user_id, payment_id: int):
    user = _load_user(db, current_user_id)
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin and superadmin can do this.")

    pay = db.query(FundPayment).filter(FundPayment.id == payment_id).with_for_update().first()
    if not pay:
        raise HTTPException(status_code=404, detail="Payment not found.")

    sangha = db.query(Sanghas).filter(Sanghas.id == pay.sangha_id).first()
    if user.role == "admin" and (not sangha or sangha.admin_id != user.id):
        raise HTTPException(status_code=403, detail="You do not manage this Sangha.")
    if pay.member_id == user.id:
        raise HTTPException(status_code=403, detail="You cannot act on your own payment.")
    if pay.status != "Pending":
        raise HTTPException(status_code=400, detail="This payment has already been reviewed.")
    return user, pay


# ---------------- member: report a payment ----------------
@app.post("/sangha-savings/payments")
def create_fund_payment(
    payload: FundPaymentCreate,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = _load_user(db, current_user_id)
    if user.role != "member":
        raise HTTPException(status_code=403, detail="Only members can make payments.")

    target = next((d for d in _member_debts(db, user.id) if d["req"].id == payload.request_id), None)
    if not target:
        raise HTTPException(status_code=400, detail="That debt was not found or is already fully repaid.")

    due = target["interest"] if payload.kind == "interest" else target["outstanding"]
    if due <= 0:
        raise HTTPException(
            status_code=400,
            detail="No interest is due on this debt right now." if payload.kind == "interest"
            else "Nothing is outstanding on this debt.",
        )
    if payload.amount > due:
        raise HTTPException(status_code=422, detail=f"The most you can pay now is ₹{due:,.2f}.")

    # The payment (interest or principal) must be covered by the member's bank balance
    _require_balance(db, user, payload.amount, f"{payload.kind} payment")

    req = target["req"]
    sangha = db.query(Sanghas).filter(Sanghas.id == req.sangha_id).first()

    ref = payload.reference.strip()
    if db.query(FundPayment.id).filter(
        FundPayment.reference == ref, FundPayment.status.in_(("Pending", "Confirmed"))
    ).first():
        raise HTTPException(status_code=409, detail="This transaction reference was already submitted.")

    pay = FundPayment(
        request_id=req.id, sangha_id=req.sangha_id, member_id=user.id,
        kind=payload.kind, amount=payload.amount, reference=payload.reference.strip(), status="Pending",
    )
    db.add(pay)
    db.flush()

    if sangha and sangha.admin_id:
        _notify_user(
            db, user.id, sangha.admin_id, "Payment to confirm",
            f"{user.fullname} reports paying ₹{payload.amount:,.2f} as {payload.kind} "
            f"(reference {pay.reference}). Please confirm once the money is received.",
            req.sangha_id,
        )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"You already have a {payload.kind} payment waiting for confirmation.")

    return {"message": "Payment submitted. It will be recorded once the admin confirms it.", "paymentId": pay.id}


# ---------------- admin: list, confirm, reject ----------------
@app.get("/sangha-savings/payments/pending")
def list_pending_fund_payments(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = _load_user(db, current_user_id)
    rows = (
        _payments_query(db, user)
        .filter(FundPayment.status == "Pending")
        .order_by(FundPayment.created_at.asc())
        .all()
    )
    return {
        "items": [
            {
                "id": p.id,
                "requestId": p.request_id,
                "memberName": m.fullname,
                "sanghaName": s.name,
                "kind": p.kind,
                "amount": float(p.amount),
                "reference": p.reference,
                "createdAt": p.created_at.isoformat(),
            }
            for p, s, m in rows
        ]
    }


@app.post("/sangha-savings/payments/{payment_id}/confirm")
def confirm_fund_payment(
    payment_id: int,
    payload: FundPaymentConfirm,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user, pay = _staff_payment(db, current_user_id, payment_id)
    req = db.query(FundRequest).filter(FundRequest.id == pay.request_id).with_for_update().first()

    principal = pay.amount if pay.kind == "principal" else ZERO
    interest = pay.amount if pay.kind == "interest" else ZERO
    result = _apply_repayment(db, user, req, _d(principal), _d(interest), payload.is_on_time)
    _apply_balance_change(db, pay.member_id, -_d(pay.amount))           # debit the member

    pay.status = "Confirmed"
    pay.reviewed_by = user.id
    pay.reviewed_at = datetime.utcnow()
    db.commit()
    return {"detail": "Payment confirmed.", **result}


@app.post("/sangha-savings/payments/{payment_id}/reject")
def reject_fund_payment(
    payment_id: int,
    payload: FundPaymentReject,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user, pay = _staff_payment(db, current_user_id, payment_id)
    pay.status = "Rejected"
    pay.rejection_reason = payload.reason.strip()
    pay.reviewed_by = user.id
    pay.reviewed_at = datetime.utcnow()

    _notify_user(
        db, user.id, pay.member_id, "Payment not received",
        f"Your {pay.kind} payment of ₹{pay.amount:,.2f} (reference {pay.reference}) could not be "
        f"confirmed.\n\nReason: {pay.rejection_reason}\n\nPlease check the reference and try again.",
        pay.sangha_id,
    )
    db.commit()
    return {"detail": "Payment rejected."}


# =====================================================================
# SANGHA CONTRIBUTIONS (every member, every day, debt or not)
# =====================================================================

CONTRIBUTION_PER_DAY = Decimal("100")   # Sangha rule: change here if the rule changes


def _today_ist() -> date:
    """Today's date in India, so a payment at 7 AM IST is not treated as yesterday."""
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).date()


# ---------------- member: this month's calendar ----------------
@app.get("/sangha-savings/contributions")
def get_my_contributions(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = _load_user(db, current_user_id)
    if user.role != "member":
        raise HTTPException(status_code=403, detail="Only members have contributions.")

    today = _today_ist()
    n = calendar.monthrange(today.year, today.month)[1]
    first, last = today.replace(day=1), today.replace(day=n)

    rows = (
        db.query(Contribution)
        .filter(
            Contribution.member_id == user.id,
            Contribution.status.in_(("Pending", "Confirmed")),
            Contribution.for_date >= first,
            Contribution.for_date <= last,
        )
        .all()
    )
    by_date = {r.for_date: r.status for r in rows}

    days, due_days = [], 0
    for i in range(1, n + 1):
        d = today.replace(day=i)
        st = by_date.get(d)
        if st == "Confirmed":
            state = "paid"
        elif st == "Pending":
            state = "waiting"
        elif d < today:
            state = "missed"
        elif d == today:
            state = "due"
        else:
            state = "upcoming"
        if state in ("missed", "due"):
            due_days += 1
        days.append({"date": d.isoformat(), "day": i, "state": state})

    paid_days = sum(1 for x in days if x["state"] == "paid")
    paid_amount = sum((_d(r.amount) for r in rows if r.status == "Confirmed"), ZERO)

    year_total = (
        db.query(func.coalesce(func.sum(Contribution.amount), 0))
        .filter(
            Contribution.member_id == user.id,
            Contribution.status == "Confirmed",
            Contribution.for_date >= today.replace(month=1, day=1),
        )
        .scalar()
    )

    # History, grouped by the payment (batch) the member made
    all_rows = (
        db.query(Contribution)
        .filter(Contribution.member_id == user.id)
        .order_by(Contribution.created_at.desc())
        .limit(300)
        .all()
    )
    batches: dict = {}
    for r in all_rows:
        b = batches.setdefault(r.batch_id, {
            "batchId": r.batch_id, "reference": r.reference, "amount": ZERO, "days": [],
            "status": r.status, "createdAt": r.created_at.isoformat(),
            "rejectionReason": r.rejection_reason,
        })
        b["amount"] += _d(r.amount)
        b["days"].append(r.for_date.isoformat())
    history = []
    for b in list(batches.values())[:50]:
        b["days"].sort()
        history.append({**b, "amount": float(b["amount"])})

    account = _account_for(db, user.sangha_id) if user.sangha_id else None
    blocker = None
    if not user.sangha_id:
        blocker = "You are not currently assigned to a Sangha."
    elif not account or account.status != "Active":
        blocker = "No active Sangha Savings Account is available."

    return {
        "month": today.strftime("%B %Y"),
        "today": today.isoformat(),
        "daysInMonth": n,
        "dailyAmount": float(CONTRIBUTION_PER_DAY),
        "monthlyAmount": float(CONTRIBUTION_PER_DAY * n),
        "days": days,
        "daysPaid": paid_days,
        "paidAmount": float(paid_amount),
        "remaining": float(CONTRIBUTION_PER_DAY * n - paid_amount),
        "dueNow": float(CONTRIBUTION_PER_DAY * due_days),
        "yearTotal": float(_d(year_total)),
        "history": history,
        "canPay": blocker is None,
        "payBlocker": blocker,
    }


# ---------------- member: report a contribution payment ----------------
@app.post("/sangha-savings/contributions")
def create_contribution(
    payload: ContributionCreate,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = _load_user(db, current_user_id)
    if user.role != "member":
        raise HTTPException(status_code=403, detail="Only members can pay contributions.")
    if not user.sangha_id:
        raise HTTPException(status_code=400, detail="You are not currently assigned to a Sangha.")

    sangha = db.query(Sanghas).filter(Sanghas.id == user.sangha_id).first()
    account = _account_for(db, user.sangha_id)
    if not sangha or not account or account.status != "Active":
        raise HTTPException(status_code=400, detail="No active Sangha Savings Account is available.")

    today = _today_ist()
    dates = sorted(set(payload.dates))
    for d in dates:
        if d.year != today.year or d.month != today.month:
            raise HTTPException(status_code=422, detail="You can only pay for days in the current month.")
        if d > today:
            raise HTTPException(status_code=422, detail="You cannot pay for a future day.")

    taken = (
        db.query(Contribution.id)
        .filter(
            Contribution.member_id == user.id,
            Contribution.for_date.in_(dates),
            Contribution.status.in_(("Pending", "Confirmed")),
        )
        .first()
    )
    if taken:
        raise HTTPException(status_code=409, detail="Some of these days are already paid or waiting for confirmation.")

    # The whole contribution (all selected days) must be covered by the bank balance
    _require_balance(db, user, CONTRIBUTION_PER_DAY * len(dates), "contribution")

    now = datetime.utcnow()
    batch_id = str(uuid.uuid4())
    for d in dates:
        db.add(Contribution(
            batch_id=batch_id, member_id=user.id, sangha_id=sangha.id, for_date=d,
            amount=CONTRIBUTION_PER_DAY, reference=payload.reference.strip(),
            status="Pending", created_at=now,
        ))

    total = CONTRIBUTION_PER_DAY * len(dates)
    if sangha.admin_id:
        _notify_user(
            db, user.id, sangha.admin_id, "Contribution to confirm",
            f"{user.fullname} reports paying a Sangha contribution of ₹{total:,.2f} for {len(dates)} day(s) "
            f"(reference {payload.reference.strip()}). Please confirm once the money is received.",
            sangha.id,
        )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Some of these days are already paid or waiting for confirmation.")

    return {"message": "Contribution submitted. It counts once the admin confirms it.", "batchId": batch_id}


# ---------------- admin: list, confirm, reject ----------------
def _contributions_query(db: Session, user: User):
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin and superadmin can view contributions.")
    q = (
        db.query(Contribution, Sanghas, User)
        .join(Sanghas, Sanghas.id == Contribution.sangha_id)
        .join(User, User.id == Contribution.member_id)
        .filter(Contribution.member_id != user.id)
    )
    if user.role == "admin":
        q = q.filter(Sanghas.admin_id == user.id)
    return q


@app.get("/sangha-savings/contributions/pending")
def list_pending_contributions(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = _load_user(db, current_user_id)
    rows = (
        _contributions_query(db, user)
        .filter(Contribution.status == "Pending")
        .order_by(Contribution.created_at.asc(), Contribution.for_date.asc())
        .all()
    )
    batches: dict = {}
    for c, s, m in rows:
        b = batches.setdefault(c.batch_id, {
            "batchId": c.batch_id, "memberName": m.fullname, "sanghaName": s.name,
            "reference": c.reference, "amount": ZERO, "days": [], "createdAt": c.created_at.isoformat(),
        })
        b["amount"] += _d(c.amount)
        b["days"].append(c.for_date.isoformat())
    return {"items": [{**b, "amount": float(b["amount"])} for b in batches.values()]}


def _staff_contribution_batch(db: Session, current_user_id, batch_id: str):
    user = _load_user(db, current_user_id)
    if user.role not in ("admin", "superadmin"):
        raise HTTPException(status_code=403, detail="Only admin and superadmin can do this.")

    rows = (
        db.query(Contribution)
        .filter(Contribution.batch_id == batch_id, Contribution.status == "Pending")
        .with_for_update()
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Contribution not found or already reviewed.")

    sangha = db.query(Sanghas).filter(Sanghas.id == rows[0].sangha_id).first()
    if user.role == "admin" and (not sangha or sangha.admin_id != user.id):
        raise HTTPException(status_code=403, detail="You do not manage this Sangha.")
    if rows[0].member_id == user.id:
        raise HTTPException(status_code=403, detail="You cannot act on your own contribution.")
    return user, rows


@app.post("/sangha-savings/contributions/{batch_id}/confirm")
def confirm_contribution(
    batch_id: str,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user, rows = _staff_contribution_batch(db, current_user_id, batch_id)
    total = sum((_d(r.amount) for r in rows), ZERO)

    account = _account_for(db, rows[0].sangha_id, lock=True)
    if not account:
        raise HTTPException(status_code=400, detail="No Sangha Savings Account found.")

    _store_balance(account, _balance(account) + total)   # contributions grow the Sangha fund
    _apply_balance_change(db, rows[0].member_id, -total)  # debit the member

    now = datetime.utcnow()
    for r in rows:
        r.status = "Confirmed"
        r.reviewed_by = user.id
        r.reviewed_at = now

    _notify_user(
        db, user.id, rows[0].member_id, "Contribution confirmed",
        f"Your Sangha contribution of ₹{total:,.2f} for {len(rows)} day(s) has been received. Thank you.",
        rows[0].sangha_id,
    )
    db.commit()
    return {"detail": "Contribution confirmed.", "amount": float(total)}


@app.post("/sangha-savings/contributions/{batch_id}/reject")
def reject_contribution(
    batch_id: str,
    payload: FundPaymentReject,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user, rows = _staff_contribution_batch(db, current_user_id, batch_id)
    total = sum((_d(r.amount) for r in rows), ZERO)

    now = datetime.utcnow()
    for r in rows:
        r.status = "Rejected"
        r.rejection_reason = payload.reason.strip()
        r.reviewed_by = user.id
        r.reviewed_at = now

    _notify_user(
        db, user.id, rows[0].member_id, "Contribution not received",
        f"Your contribution of ₹{total:,.2f} (reference {rows[0].reference}) could not be confirmed.\n\n"
        f"Reason: {payload.reason.strip()}\n\nPlease check the reference and try again.",
        rows[0].sangha_id,
    )
    db.commit()
    return {"detail": "Contribution rejected."}


@app.get("/me/employment-profile")
def get_employment_profile(
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = db.query(User).filter(
        User.id == int(current_user_id)
    ).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    if user.role != "member":
        raise HTTPException(
            status_code=403,
            detail="Only members can access this profile.",
        )

    professional = (user.professional or "").strip()
    is_house_wife = professional.casefold() == "house wife"

    completed = bool(
        is_house_wife
        or (professional and user.salary is not None)
    )

    return {
        "professional": user.professional,
        "salary": user.salary,
        "employment_type": (
            "house_wife" if is_house_wife
            else "other" if professional
            else None
        ),
        "needs_completion": not completed,
    }


@app.patch("/me/employment-profile")
def update_employment_profile(
    payload: EmploymentProfileUpdate,
    db: Session = Depends(get_db),
    current_user_id=Depends(get_current_user),
):
    user = db.query(User).filter(
        User.id == int(current_user_id)
    ).first()

    if not user:
        raise HTTPException(status_code=401, detail="User not found.")

    if user.role != "member":
        raise HTTPException(
            status_code=403,
            detail="Only members can update this profile.",
        )

    if payload.employment_type == "house_wife":
        user.professional = "House wife"
        user.salary = None

    else:
        professional = (payload.professional or "").strip()

        if not professional:
            raise HTTPException(
                status_code=422,
                detail="Please enter your profession.",
            )

        if len(professional) > 100:
            raise HTTPException(
                status_code=422,
                detail="Profession must be 100 characters or fewer.",
            )

        if payload.salary is None:
            raise HTTPException(
                status_code=422,
                detail="Please enter your monthly salary.",
            )

        user.professional = professional
        user.salary = payload.salary

    db.commit()
    db.refresh(user)

    return {
        "message": "Employment details saved successfully.",
        "professional": user.professional,
        "salary": user.salary,
        "completed": True,
    }


Base.metadata.create_all(bind=engine)