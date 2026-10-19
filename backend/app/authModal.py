import enum
from datetime import datetime, date
from decimal import Decimal
from sqlalchemy import (
    Integer, String, ForeignKey, Boolean, Enum, DateTime, Text, func, Date,
    UniqueConstraint, LargeBinary, Numeric, CheckConstraint, Index, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.dbconnection import Base


class Role(str, enum.Enum):
    superadmin = "superadmin"
    admin = "admin"
    subadmin = "subadmin"
    member = "member"


class RequestStatus(str, enum.Enum):
    pending = "PENDING"
    approved = "APPROVED"
    rejected = "REJECTED"
    not_submitted = "NOT_SUBMITTED"

class NotificationType(str, enum.Enum):
    account_verification = "Account Verification"
    profile = "Profile"
    announcement = "Announcement"
    important = "Important"


class RecipientRule(str, enum.Enum):
    all_members = "All Members"
    incomplete_profile = "Members Without Completed Profile"
    missing_banking = "Members Without Banking Details"
    incomplete_profile_or_banking = "Members Without Completed Profile or Banking Details"


class NotificationStatus(str, enum.Enum):
    draft = "Draft"
    sent = "Sent"

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fullname: Mapped[str] = mapped_column(String(50))
    username: Mapped[str] = mapped_column(String(30), unique=True)
    email: Mapped[str] = mapped_column(String(50), unique=True)
    phone: Mapped[str] = mapped_column(String(15), unique=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password: Mapped[str] = mapped_column(String(255))

    role: Mapped[Role] = mapped_column(Enum(Role), default=Role.member)
    isVerified: Mapped[bool] = mapped_column(Boolean, default=False)
    isActive: Mapped[bool] = mapped_column(Boolean, default=True)

    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    profile_photo_image: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    profile_photo_content_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ---- ID Proof: Aadhaar or Passport ----
    id_proof_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    id_proof_number_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    id_proof_number_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    id_proof_image_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    id_proof_image_content_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # ---- PAN Card ----
    pan_number_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    pan_number_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    pan_image_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    pan_image_content_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    otp: Mapped[str | None] = mapped_column(String(6), nullable=True)
    otp_expiry: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    creator: Mapped["User"] = relationship(remote_side=[id])

    sangha_id: Mapped[int | None] = mapped_column(ForeignKey("sanghas.id"), nullable=True)
        # Entered by admin/superadmin from a real report. Never calculated here.
    cibil_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cibil_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    professional: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    salary: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2),
        nullable=True,
    )

    # Money held in the member's app account (stored in this DB, not a live bank link).
    bank_balance: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=0,
        server_default="0",
    )

    sangha: Mapped["Sanghas"] = relationship(
        back_populates="members", foreign_keys=[sangha_id]
    )
    bank_balance_snapshots: Mapped[list["MemberBankBalanceSnapshot"]] = relationship(
        back_populates="member"
    )
    available_balance_snapshots: Mapped[list["MemberAvailableBalanceSnapshot"]] = relationship(
        back_populates="member"
    )


class MemberBankBalanceSnapshot(Base):
    __tablename__ = "member_bank_balance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(128), nullable=False)

    member: Mapped["User"] = relationship(back_populates="bank_balance_snapshots")

    __table_args__ = (
        Index(
            "ix_member_bank_balance_snapshots_member_recorded_at",
            "member_id",
            "recorded_at",
        ),
        UniqueConstraint(
            "member_id",
            "source",
            "source_reference",
            name="uq_member_bank_snapshot_source_reference",
        ),
    )


class MemberAvailableBalanceSnapshot(Base):
    __tablename__ = "member_available_balance_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    balance: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    snapshot_day: Mapped[date] = mapped_column(Date, nullable=False)

    member: Mapped["User"] = relationship(back_populates="available_balance_snapshots")

    __table_args__ = (
        Index(
            "ix_member_available_balance_snapshots_member_recorded_at",
            "member_id",
            "recorded_at",
        ),
        UniqueConstraint(
            "member_id",
            "snapshot_day",
            name="uq_member_available_balance_snapshot_day",
        ),
    )


class Sanghas(Base):
    __tablename__ = "sanghas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str | None] = mapped_column(String(7),unique=True,nullable=True)  # e.g. "RS042429"
    name: Mapped[str] = mapped_column(String(50), unique=True)
    address: Mapped[str] = mapped_column(String(255))
    city: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20))
    isActive: Mapped[bool] = mapped_column(Boolean, default=True)
    membersCount: Mapped[int] = mapped_column(Integer, default=0)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))            # superadmin or admin
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)   # must have role=admin
    subadmin_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True, nullable=True)

    admin: Mapped["User | None"] = relationship("User", foreign_keys=[admin_id])

    members: Mapped[list["User"]] = relationship(
        back_populates="sangha", foreign_keys="User.sangha_id"
    )
    savings_account = relationship(
        "SanghaSavingsAccount",
        back_populates="sangha",
        uselist=False,
        cascade="all, delete-orphan",
    )
    


class SubAdminRequest(Base):
    """Pending request for a member to become a sangha's subadmin — the approval workflow itself."""
    __tablename__ = "subadmin_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sangha_id: Mapped[int] = mapped_column(ForeignKey("sanghas.id"))
    admin_id: Mapped[int] = mapped_column(ForeignKey("users.id"))     # reviewer
    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"))  # the member requesting/proposed

    # Snapshot of submitted details (kept even if the user later edits their profile)
    subadmin_name: Mapped[str] = mapped_column(String(50))
    subadmin_email: Mapped[str] = mapped_column(String(50))
    subadmin_phone: Mapped[str] = mapped_column(String(15))
    address: Mapped[str] = mapped_column(String(255))
    aadhar_number: Mapped[str] = mapped_column(String(20))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    experience: Mapped[str | None] = mapped_column(Text, nullable=True)
    qualifications: Mapped[str | None] = mapped_column(Text, nullable=True)
    availability: Mapped[str | None] = mapped_column(String(100), nullable=True)
    additional_info: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[RequestStatus] = mapped_column(Enum(RequestStatus), default=RequestStatus.pending)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SubAdminActivityLog(Base):
    __tablename__ = "subadmin_activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subadmin_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(50))
    performed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # 45 = IPv6-safe

class BankDetails(Base):
    __tablename__ = "bank_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)

    account_number_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    account_holder_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bank_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    account_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ifsc_code: Mapped[str | None] = mapped_column(String(11), nullable=True)
    branch_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, onupdate=func.now(), nullable=True)
    
class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType))
    recipient: Mapped[RecipientRule] = mapped_column(Enum(RecipientRule), default=RecipientRule.all_members)
    message: Mapped[str] = mapped_column(Text)
    navigation_path: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list of steps
    status: Mapped[NotificationStatus] = mapped_column(Enum(NotificationStatus), default=NotificationStatus.draft)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sangha_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of sangha ids; null/empty = All Sanghas


class NotificationRecipient(Base):
    """Snapshot of who actually received a notification, taken at send time."""
    __tablename__ = "notification_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notification_id: Mapped[int] = mapped_column(ForeignKey("notifications.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("notification_id", "user_id", name="uq_notification_recipient"),)

class SanghaSavingsAccount(Base):
    __tablename__ = "sangha_savings_accounts"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    sangha_id: Mapped[int] = mapped_column(
        ForeignKey("sanghas.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    account_holder_enc: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    bank_name_enc: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    account_number_enc: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    ifsc_code_enc: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    branch_name_enc: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    account_type_enc: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    balance_enc: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="Active",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # -----------------------------------------
    # Relationship → Sangha
    # -----------------------------------------

    sangha: Mapped["Sanghas"] = relationship(
        "Sanghas",
        back_populates="savings_account",
    )

class LoanStatus(str, enum.Enum):
    pending = "Pending"        # member asked for a loan
    approved = "Approved"      # approved, money not yet given
    rejected = "Rejected"
    disbursed = "Disbursed"    # money given: this is when debt starts
    closed = "Closed"          # fully repaid


class Loan(Base):
    __tablename__ = "loans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sangha_id: Mapped[int] = mapped_column(ForeignKey("sanghas.id"), index=True)

    amount_requested: Mapped[float] = mapped_column(Numeric(12, 2))
    amount_approved: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[LoanStatus] = mapped_column(Enum(LoanStatus), default=LoanStatus.pending)
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("amount_requested > 0", name="ck_loan_amount_positive"),
    )


class LoanRepayment(Base):
    """Without this, debt could never go back down."""
    __tablename__ = "loan_repayments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"), index=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    paid_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_repayment_positive"),
    )


class VerificationRequest(Base):
    __tablename__ = "verification_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[RequestStatus] = mapped_column(Enum(RequestStatus), default=RequestStatus.pending)
    requested_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # At most one pending request per member, enforced by the database
    __table_args__ = (
        Index(
            "uq_one_pending_verification",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

class FundRequestStatus(str, enum.Enum):
    pending = "Pending"
    under_review = "Under Review"
    approved = "Approved"
    rejected = "Rejected"
    disbursed = "Disbursed"
    repaying = "Repaying"
    completed = "Completed"


class FundRequest(Base):
    """Member emergency money request: Sangha Savings -> Member. NOT the Sangha bank loan."""
    __tablename__ = "fund_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sangha_id: Mapped[int] = mapped_column(ForeignKey("sanghas.id"), index=True)

    amount_requested: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    amount_approved: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    monthly_salary: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    reason: Mapped[str] = mapped_column(Text)

    status: Mapped[FundRequestStatus] = mapped_column(Enum(FundRequestStatus), default=FundRequestStatus.pending)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    disbursed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("amount_requested > 0", name="ck_fund_request_amount_positive"),
        # A member can have only one open request at a time (stops double submits at DB level)
        Index(
            "uq_one_open_fund_request", "member_id", unique=True,
            postgresql_where=text("status IN ('pending','under_review','approved')"),
        ),
    )


class FundRepayment(Base):
    __tablename__ = "fund_repayments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("fund_requests.id"), index=True)
    sangha_id: Mapped[int] = mapped_column(ForeignKey("sanghas.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    principal: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    interest: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    is_on_time: Mapped[bool] = mapped_column(Boolean, default=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))

    __table_args__ = (
        CheckConstraint("principal >= 0 AND interest >= 0 AND principal + interest > 0", name="ck_fund_repayment_amount"),
    )


class FundTransaction(Base):
    """Ledger of money movement. kind: disbursement | repayment | interest"""
    __tablename__ = "fund_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sangha_id: Mapped[int] = mapped_column(ForeignKey("sanghas.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("fund_requests.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class FundPayment(Base):
    """A payment the member says they made. It counts only after an admin confirms it."""
    __tablename__ = "fund_payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("fund_requests.id"), index=True)
    sangha_id: Mapped[int] = mapped_column(ForeignKey("sanghas.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(10))            # "interest" | "principal"
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    reference: Mapped[str] = mapped_column(String(60))       # UPI / bank transaction ID
    status: Mapped[str] = mapped_column(String(12), default="Pending")   # Pending | Confirmed | Rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_fund_payment_amount_positive"),
        # One waiting payment per member per type: stops double submits at DB level
        Index(
            "uq_one_pending_fund_payment", "member_id", "kind", unique=True,
            postgresql_where=text("status = 'Pending'"),
        ),
    )

class Contribution(Base):
    """One row per day a member pays towards the Sangha. Counts only once an admin confirms it."""
    __tablename__ = "contributions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)     # rows paid together share one batch
    member_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    sangha_id: Mapped[int] = mapped_column(ForeignKey("sanghas.id"), index=True)
    for_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    reference: Mapped[str] = mapped_column(String(60))                # UPI / bank transaction ID
    status: Mapped[str] = mapped_column(String(12), default="Pending")   # Pending | Confirmed | Rejected
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_contribution_amount_positive"),
        # A day can be paid once. A rejected day can be paid again.
        Index(
            "uq_contribution_day", "member_id", "for_date", unique=True,
            postgresql_where=text("status IN ('Pending','Confirmed')"),
        ),
    )