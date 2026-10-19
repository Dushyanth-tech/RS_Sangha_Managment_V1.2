from datetime import date, datetime
from enum import Enum
from pydantic import BaseModel, EmailStr, field_validator, Field
from decimal import Decimal
from typing import Literal
import re


def validate_password_strength(val: str) -> str:
    if len(val) < 8:
        raise ValueError("Password must be at least 8 characters")
    if not re.search(r"[a-z]", val):
        raise ValueError("Password must contain at least one lowercase letter")
    if not re.search(r"\d", val):
        raise ValueError("Password must contain at least one number")
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+=/\\[\]]", val):
        raise ValueError("Password must contain at least one special character")
    return val


class NewUser(BaseModel):
    username: str
    fullname: str
    email: EmailStr
    phone: str
    password: str
    confirm_password: str
    aadhar_number: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, val: str) -> str:
        return validate_password_strength(val)

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, val: str, info) -> str:
        if "password" in info.data and val != info.data["password"]:
            raise ValueError("Passwords do not match")
        return val


class LoginUser(BaseModel):
    email: str
    password: str

class NewSanghas(BaseModel):
    name: str
    address: str
    city: str
    state: str
    admin_id: int | None = None

class Search(BaseModel):
    name: str
    email:str
    phone:str
    status:bool

class AdminRequestCreate(BaseModel):
    sangha_id: int
    requester_id: int
    message: str


class AdminRequestResponse(BaseModel):
    id: int
    sangha_name: str
    candidate_name: str
    candidate_email: str
    candidate_phone: str | None
    message: str | None
    status: str
    rejection_reason: str | None

class AddAdminRequest(BaseModel):
    member_id: int
    sangha_id: int

class RemoveSanghasPayload(BaseModel):
    sangha_ids: list[int]

class SanghaUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None

class AccountType(str, Enum):
    savings = "savings"
    current = "current"

class ProfileDetailsUpdate(BaseModel):
    fullname: str | None = None
    date_of_birth: date | None = None
    phone: str | None = None
    address: str | None = None
    aadhar_number: str | None = None

    @field_validator("aadhar_number")
    @classmethod
    def validate_aadhar(cls, v):
        if not v:
            return v
        digits = re.sub(r"\D", "", v)
        if len(digits) != 12:
            raise ValueError("Aadhar number must be 12 digits")
        return digits

class BankDetailsUpdate(BaseModel):
    pan_number: str | None = None
    account_number: str | None = None
    account_holder_name: str | None = None
    bank_name: str | None = None
    account_type: AccountType | None = None
    ifsc_code: str | None = None
    branch_name: str | None = None

    @field_validator("pan_number")
    @classmethod
    def validate_pan(cls, v):
        if not v:
            return v
        v = v.upper().strip()
        if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", v):
            raise ValueError("Invalid PAN format")
        return v

    @field_validator("ifsc_code")
    @classmethod
    def validate_ifsc(cls, v):
        if not v:
            return v
        v = v.upper().strip()
        if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", v):
            raise ValueError("Invalid IFSC code")
        return v

    @field_validator("account_number")
    @classmethod
    def validate_account_number(cls, v):
        if not v:
            return v
        digits = re.sub(r"\D", "", v)
        if not (9 <= len(digits) <= 18):
            raise ValueError("Account number length looks invalid")
        return digits

class ProfileWizardUpdate(BaseModel):
    profile: ProfileDetailsUpdate | None = None
    banking: BankDetailsUpdate | None = None

ALLOWED_TYPES = {"Account Verification", "Profile", "Announcement", "Important"}
ALLOWED_RECIPIENTS = {
    "All Members",
    "Members Without Completed Profile",
    "Members Without Banking Details",
    "Members Without Completed Profile or Banking Details",
}


class NotificationCreate(BaseModel):
    title: str
    type: str = "Announcement"
    recipient: str = "All Members"
    message: str
    include_path: bool = False
    navigation_path: list[str] | None = None
    send_now: bool = False

    @field_validator("type")
    @classmethod
    def validate_type(cls, v):
        if v not in ALLOWED_TYPES:
            raise ValueError(f"type must be one of {ALLOWED_TYPES}")
        return v

    @field_validator("recipient")
    @classmethod
    def validate_recipient(cls, v):
        if v not in ALLOWED_RECIPIENTS:
            raise ValueError(f"recipient must be one of {ALLOWED_RECIPIENTS}")
        return v

class NotificationCreate(BaseModel):
    title: str
    type: str = "Announcement"
    recipient: str = "All Members"
    sangha_ids: list[int] | None = None   # None/empty = All Sanghas
    message: str
    include_path: bool = False
    navigation_path: list[str] | None = None
    send_now: bool = False
    # ...same validators as before


class ClearNotificationsRequest(BaseModel):
    notification_ids: list[int]


class SanghaSavingsAccountCreate(BaseModel):
    sangha_id: int
    account_holder: str = Field(..., min_length=2)
    bank: str = Field(..., min_length=2)
    account_number: str
    ifsc: str
    branch: str = Field(..., min_length=2)
    account_type: str = "Savings"

class CibilUpdate(BaseModel):
    score: int = Field(..., ge=300, le=900)

class FundRequestCreate(BaseModel):
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    monthly_salary: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    reason: str = Field(..., min_length=10, max_length=500)


class FundRequestReview(BaseModel):
    action: Literal["start_review", "approve", "reject"]
    approved_amount: Decimal | None = Field(None, gt=0, max_digits=12, decimal_places=2)
    reason: str | None = Field(None, max_length=255)


class FundRepaymentCreate(BaseModel):
    principal: Decimal = Field(..., ge=0, max_digits=12, decimal_places=2)
    interest: Decimal = Field(0, ge=0, max_digits=12, decimal_places=2)
    is_on_time: bool = True


class FundPaymentCreate(BaseModel):
    request_id: int
    kind: Literal["interest", "principal"]
    amount: Decimal = Field(..., gt=0, max_digits=12, decimal_places=2)
    reference: str = Field(..., min_length=6, max_length=60)


class FundPaymentConfirm(BaseModel):
    is_on_time: bool = True


class FundPaymentReject(BaseModel):
    reason: str = Field(..., min_length=3, max_length=255)

class ContributionCreate(BaseModel):
    dates: list[date] = Field(..., min_length=1, max_length=31)
    reference: str = Field(..., min_length=6, max_length=60)


class MemberBankBalanceSnapshotResponse(BaseModel):
    id: int
    balance: Decimal
    recorded_at: datetime
    source: str

    model_config = {"from_attributes": True}


class MemberBankBalanceSnapshotCreateResponse(BaseModel):
    snapshot: MemberBankBalanceSnapshotResponse
    created: bool


class MemberAvailableBalanceSnapshotResponse(BaseModel):
    id: int
    balance: Decimal
    recorded_at: datetime

    model_config = {"from_attributes": True}


class MemberAvailableBalanceSnapshotCreateResponse(BaseModel):
    snapshot: MemberAvailableBalanceSnapshotResponse
    created: bool


class EmploymentProfileUpdate(BaseModel):
    employment_type: Literal["house_wife", "other"]
    professional: str | None = None
    salary: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
    )


class CreditScoreFactor(BaseModel):
    key: str
    label: str
    weight: int          # percent of the total score
    score: float         # 0-100


class CreditScoreResponse(BaseModel):
    """RS-Sangha INTERNAL score. Not an official CIBIL score."""
    score: int | None
    min_score: int
    max_score: int
    category: str | None
    status: Literal["sufficient", "insufficient_data"]
    missing: list[str] = []
    calculated_at: datetime
    factors: list[CreditScoreFactor] = []