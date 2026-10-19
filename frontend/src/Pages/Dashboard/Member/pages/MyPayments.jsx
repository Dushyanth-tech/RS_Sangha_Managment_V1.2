import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Wallet,
  Percent,
  Banknote,
  HandCoins,
  Landmark,
  Download,
  Search,
  Receipt,
  ArrowRight,
  X,
  Loader2,
  Clock,
  PiggyBank,
  CheckCircle2,
} from "lucide-react";

import api from "../../../../api/axiosInstance";
import "./MyPayments.css";

/* ====================================================================
   HELPERS
==================================================================== */

const NA = "Not available yet";

const rupees = (v) =>
  v === null || v === undefined
    ? NA
    : `₹${Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;

const fmtDate = (iso) =>
  iso
    ? new Date(iso).toLocaleDateString("en-IN", {
        day: "2-digit",
        month: "short",
        year: "numeric",
      })
    : "—";

const dayShort = (iso) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
  });

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

const errorText = (err, fallback) => {
  if (err?.response?.status === 401) {
    return "Your session has expired. Please log in again.";
  }
  const detail = err?.response?.data?.detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join(", ");
  return (typeof detail === "string" && detail) || fallback;
};

const FILTERS = ["All", "Contributions", "Interest", "Principal", "Pending", "Failed"];

const FILTER_TEST = {
  All: () => true,
  Contributions: (p) => p.kind === "Contribution",
  Interest: (p) => p.kind === "Interest",
  Principal: (p) => p.kind === "Principal",
  Pending: (p) => p.status === "Pending",
  Failed: (p) => p.status === "Failed",
};

const STATUS_TONE = { Paid: "green", Pending: "orange", Failed: "red" };

// A confirmed repayment from the ledger. Money RECEIVED is not a payment, so it is filtered out earlier.
const toPayment = (t) => {
  const label = t.type || "";
  const kind = label.startsWith("Repayment")
    ? "Principal"
    : label.startsWith("Interest")
      ? "Interest"
      : "Other";
  return {
    id: t.id,
    kind,
    type: kind === "Other" ? label : kind,
    amount: t.amount,
    date: t.date,
    ref: `RS-TXN-${String(t.id).padStart(6, "0")}`,
    status: t.status === "Completed" ? "Paid" : t.status,
  };
};

/* ====================================================================
   SMALL UI PIECES
==================================================================== */

const Skel = ({ w = "100%", h = 18 }) => (
  <span className="mp-skel" style={{ width: w, height: h }} />
);

const Badge = ({ tone = "blue", children }) => (
  <span className={`mp-badge mp-badge--${tone}`}>{children}</span>
);

const Empty = ({ icon: Icon = Receipt, text, children }) => (
  <div className="mp-empty">
    <Icon size={22} />
    <p>{text}</p>
    {children}
  </div>
);

const ErrorBox = ({ text, onRetry }) => (
  <div className="mp-error" role="alert">
    <span>{text}</span>
    {onRetry && (
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    )}
  </div>
);

const Card = ({ className = "", title, subtitle, children }) => (
  <section className={`mp-card ${className}`}>
    <div className="mp-card__head">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
    </div>
    {children}
  </section>
);

function Stat({ icon: Icon, label, value, desc, loading, tone, wide }) {
  return (
    <article className={`mp-stat ${wide ? "mp-stat--wide" : ""}`}>
      <span className={`mp-stat__icon ${tone ? `mp-stat__icon--${tone}` : ""}`}>
        <Icon size={18} />
      </span>
      <span className="mp-stat__label">{label}</span>
      {loading ? (
        <Skel w="70%" h={24} />
      ) : (
        <strong className={`mp-stat__value ${value === NA ? "mp-na" : ""}`}>{value}</strong>
      )}
      <span className="mp-stat__desc">{desc}</span>
    </article>
  );
}

function KV({ label, value }) {
  return (
    <div className="mp-kv__item">
      <dt>{label}</dt>
      <dd>{value || "—"}</dd>
    </div>
  );
}

/* ====================================================================
   CONTRIBUTION CALENDAR
==================================================================== */

function Calendar({ days, selected, onToggle }) {
  const blanks = new Date(`${days[0].date}T00:00:00`).getDay();
  const weekdays = ["S", "M", "T", "W", "T", "F", "S"];

  return (
    <div>
      <div className="mp-cal">
        {weekdays.map((w, i) => (
          <span key={`w${i}`} className="mp-cal__wd">
            {w}
          </span>
        ))}
        {Array.from({ length: blanks }).map((_, i) => (
          <span key={`b${i}`} />
        ))}
        {days.map((d) => {
          const payable = d.state === "missed" || d.state === "due";
          const isSelected = selected.has(d.date);
          const cls = `mp-cal__day mp-cal__day--${d.state} ${isSelected ? "mp-cal__day--sel" : ""}`;

          return payable ? (
            <button
              key={d.date}
              type="button"
              className={cls}
              aria-pressed={isSelected}
              aria-label={`${dayShort(d.date)}, ${d.state === "missed" ? "missed" : "due today"}`}
              onClick={() => onToggle(d.date)}
            >
              {d.day}
            </button>
          ) : (
            <span key={d.date} className={cls}>
              {d.day}
            </span>
          );
        })}
      </div>

      <ul className="mp-legend">
        <li><i className="mp-dot mp-dot--paid" /> Paid</li>
        <li><i className="mp-dot mp-dot--waiting" /> Waiting for admin</li>
        <li><i className="mp-dot mp-dot--missed" /> Missed</li>
        <li><i className="mp-dot mp-dot--due" /> Due / upcoming</li>
      </ul>
    </div>
  );
}

function ContributionCard({
  con,
  loading,
  error,
  onRetry,
  selected,
  onToggle,
  onSelectAll,
  onClear,
  onPay,
}) {
  const payable = (con?.days ?? []).filter((d) => d.state === "missed" || d.state === "due");
  const count = selected.size;
  const allSelected = payable.length > 0 && count === payable.length;
  const pct = con ? Math.min(Math.round((con.daysPaid / con.daysInMonth) * 100), 100) : 0;

  return (
    <Card
      className="mp-contrib"
      title="Sangha Contribution"
      subtitle={
        con
          ? `${con.month} · every member pays ${rupees(con.dailyAmount)} a day, with or without a debt`
          : "Every member pays this, with or without a debt"
      }
    >
      {loading ? (
        <Skel h={260} />
      ) : error ? (
        <ErrorBox text={error} onRetry={onRetry} />
      ) : !con ? null : (
        <>
          <dl className="mp-kv mp-kv--4">
            <KV label="Daily Contribution" value={rupees(con.dailyAmount)} />
            <KV label="Days Paid" value={`${con.daysPaid} / ${con.daysInMonth}`} />
            <KV label="Paid This Month" value={rupees(con.paidAmount)} />
            <KV label="Remaining" value={rupees(con.remaining)} />
          </dl>

          <div className="mp-progress">
            <div className="mp-progress__top">
              <span>Month progress</span>
              <strong>{pct}%</strong>
            </div>
            <div className="mp-bar" role="img" aria-label={`${pct}% of the month paid`}>
              <span style={{ width: `${pct}%` }} />
            </div>
          </div>

          <Calendar days={con.days} selected={selected} onToggle={onToggle} />

          {con.payBlocker && <p className="mp-note">{con.payBlocker}</p>}

          {payable.length > 0 ? (
            <>
              <p className="mp-hint">Tap the red or highlighted days to choose what you are paying for.</p>
              <div className="mp-contrib__actions">
                <button
                  type="button"
                  className="mp-btn"
                  disabled={!con.canPay}
                  onClick={allSelected ? onClear : onSelectAll}
                >
                  {allSelected ? "Clear selection" : `Select all due days (${payable.length})`}
                </button>
                <button
                  type="button"
                  className="mp-btn mp-btn--primary"
                  disabled={!con.canPay || count === 0}
                  onClick={onPay}
                >
                  {count > 0
                    ? `Pay ${rupees(count * con.dailyAmount)} for ${plural(count, "day")}`
                    : "Choose days to pay"}
                </button>
              </div>
            </>
          ) : (
            <p className="mp-note mp-note--ok">You are up to date for this month.</p>
          )}
        </>
      )}
    </Card>
  );
}

/* ====================================================================
   PAY MODAL (member reports a payment; the admin confirms it)
   Used for contributions, interest and principal.
==================================================================== */

function PayModal({ title, subtitle, amount: initial, editable, max, account, submit, onClose, onDone }) {
  const [amount, setAmount] = useState(String(initial));
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const lock = useRef(false);

  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && closeRef.current();
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, []);

  const send = async () => {
    const n = Number(amount);
    if (!(n > 0)) return setError("Enter an amount greater than ₹0.");
    if (n > max) return setError(`The most you can pay now is ${rupees(max)}.`);
    if (reference.trim().length < 6) {
      return setError("Enter the UPI / bank transaction ID (at least 6 characters).");
    }
    if (lock.current) return;

    lock.current = true;
    setBusy(true);
    setError("");
    try {
      await submit(n, reference.trim());
      setSent(true);
      onDone();
    } catch (err) {
      console.error("Payment failed:", err);
      setError(errorText(err, "Unable to submit the payment."));
      lock.current = false;
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mp-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="mp-modal" role="dialog" aria-modal="true" aria-label={title}>
        <header className="mp-modal__head">
          <div>
            <h3>{title}</h3>
            <p>{subtitle}</p>
          </div>
          <button type="button" className="mp-modal__close" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>

        <div className="mp-modal__body">
          {sent ? (
            <div className="mp-sent">
              <CheckCircle2 size={40} />
              <h4>Payment submitted</h4>
              <p>
                It shows as <b>Pending</b> until the admin confirms the money was received. You will be
                notified.
              </p>
              <button type="button" className="mp-btn mp-btn--primary mp-btn--block" onClick={onClose}>
                Done
              </button>
            </div>
          ) : (
            <>
              {account && (
                <div className="mp-payto">
                  <strong>Pay to the Sangha Savings Account</strong>
                  <span>
                    {account.accountHolder} · {account.bank}
                  </span>
                  <span>
                    A/c {account.accountNumberMasked} · IFSC {account.ifsc}
                  </span>
                </div>
              )}

              <label className="mp-field">
                <span>Amount (₹)</span>
                <input
                  type="number"
                  min="1"
                  max={max}
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  readOnly={!editable}
                  disabled={busy}
                />
              </label>
              <p className="mp-hint">{editable ? `Most you can pay now: ${rupees(max)}` : "This amount is fixed."}</p>

              <label className="mp-field">
                <span>UPI / bank transaction ID</span>
                <input
                  type="text"
                  maxLength={60}
                  placeholder="Enter the reference after you pay"
                  value={reference}
                  onChange={(e) => setReference(e.target.value)}
                  disabled={busy}
                />
              </label>

              {error && <div className="mp-error">{error}</div>}

              <button
                type="button"
                className="mp-btn mp-btn--primary mp-btn--block"
                onClick={send}
                disabled={busy}
              >
                {busy && <Loader2 size={16} className="mp-spin" />}
                {busy ? "Submitting..." : "Submit Payment"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ====================================================================
   PAGE
==================================================================== */

export default function MyPayments({ onNavigate }) {
  const [ov, setOv] = useState(null);
  const [ovError, setOvError] = useState("");
  const [hist, setHist] = useState(null);
  const [histError, setHistError] = useState("");
  const [con, setCon] = useState(null);
  const [conError, setConError] = useState("");
  const [loading, setLoading] = useState(true);

  const [filter, setFilter] = useState("All");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(() => new Set());
  const [modal, setModal] = useState(null); // { type: "contribution" | "interest" | "principal", ... }

  const load = useCallback(async () => {
    setLoading(true);
    setOvError("");
    setHistError("");
    setConError("");

    const [o, h, c] = await Promise.allSettled([
      api.get("/sangha-savings/overview"),
      api.get("/sangha-savings/history"),
      api.get("/sangha-savings/contributions"),
    ]);

    if (o.status === "fulfilled") setOv(o.value.data);
    else {
      console.error("Overview failed:", o.reason);
      setOvError(errorText(o.reason, "Unable to load your payment information."));
    }

    if (h.status === "fulfilled") setHist(h.value.data);
    else {
      console.error("History failed:", h.reason);
      setHistError(errorText(h.reason, "Unable to load your payment history."));
    }

    if (c.status === "fulfilled") setCon(c.value.data);
    else {
      console.error("Contributions failed:", c.reason);
      setConError(errorText(c.reason, "Unable to load your contributions."));
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const member = ov?.member;
  const account = ov?.account;
  const sangha = ov?.sangha;

  const rate = member?.interestRate ?? 10;
  const debts = member?.debts ?? [];
  const pendingPayments = member?.pendingPayments ?? [];
  const pendingKinds = new Set(pendingPayments.map((p) => p.kind));
  const hasDebt = (member?.outstanding ?? 0) > 0;

  const payableDates = useMemo(
    () => new Set((con?.days ?? []).filter((d) => d.state === "missed" || d.state === "due").map((d) => d.date)),
    [con],
  );

  const toggleDay = (date) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(date)) next.delete(date);
      else next.add(date);
      return next;
    });

  const selectedDates = [...selected].sort();

  /* ---------- payment history (contributions + interest + principal) ---------- */
  const payments = useMemo(() => {
    const ledger = (hist?.transactions ?? []).filter((t) => t.direction === "Paid").map(toPayment);

    const waiting = (hist?.payments ?? []).map((p) => ({
      id: `p${p.id}`,
      kind: p.kind === "interest" ? "Interest" : "Principal",
      type: p.kind === "interest" ? "Interest" : "Principal",
      amount: p.amount,
      date: p.createdAt,
      ref: p.reference,
      status: p.status === "Rejected" ? "Failed" : "Pending",
      payKind: p.kind,
      requestId: p.requestId,
      reason: p.rejectionReason,
    }));

    const contributions = (con?.history ?? []).map((b) => ({
      id: `c${b.batchId}`,
      kind: "Contribution",
      type: `Contribution (${plural(b.days.length, "day")})`,
      amount: b.amount,
      date: b.createdAt,
      ref: b.reference,
      status: b.status === "Confirmed" ? "Paid" : b.status === "Rejected" ? "Failed" : "Pending",
      payKind: "contribution",
      dates: b.days,
      reason: b.rejectionReason,
    }));

    return [...waiting, ...contributions, ...ledger].sort((a, b) => new Date(b.date) - new Date(a.date));
  }, [hist, con]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return payments.filter(
      (p) =>
        FILTER_TEST[filter](p) &&
        (!q || p.ref.toLowerCase().includes(q) || p.type.toLowerCase().includes(q)),
    );
  }, [payments, filter, query]);

  const downloadReceipt = (p) => {
    const text = [
      "RS-SANGHA — PAYMENT RECEIPT",
      "---------------------------",
      `Type:           ${p.type}`,
      `Amount:         ${rupees(p.amount)}`,
      `Date:           ${fmtDate(p.date)}`,
      `Transaction ID: ${p.ref}`,
      `Status:         ${p.status}`,
    ].join("\n");
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${p.ref}.txt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  /* ---------- retry a rejected payment ---------- */
  const retryTarget = (p) => {
    if (p.payKind === "contribution") {
      const dates = (p.dates ?? []).filter((d) => payableDates.has(d));
      return dates.length > 0 && con?.canPay ? { type: "contribution", dates } : null;
    }
    const debt = debts.find((d) => d.id === p.requestId);
    if (!debt || pendingKinds.has(p.payKind)) return null;
    const open = p.payKind === "interest" ? debt.interest > 0 : debt.outstanding > 0;
    return open ? { type: p.payKind, debt } : null;
  };

  /* ---------- the modal that is open right now ---------- */
  const modalProps = (() => {
    if (!modal) return null;

    if (modal.type === "contribution") {
      const total = modal.dates.length * (con?.dailyAmount ?? 0);
      return {
        key: `con-${modal.dates.join(",")}`,
        title: "Pay Contribution",
        subtitle: `${plural(modal.dates.length, "day")} × ${rupees(con?.dailyAmount)} to the Sangha`,
        amount: total,
        max: total,
        editable: false,
        submit: (_n, reference) =>
          api.post("/sangha-savings/contributions", { dates: modal.dates, reference }),
      };
    }

    const d = modal.debt;
    const isInterest = modal.type === "interest";
    const due = isInterest ? d.interest : d.outstanding;
    return {
      key: `${modal.type}-${d.id}`,
      title: isInterest ? "Pay Interest" : "Pay Principal",
      subtitle: isInterest
        ? `${rate}% monthly interest on ${rupees(d.outstanding)}`
        : `Repay part or all of ${rupees(d.outstanding)}`,
      amount: due,
      max: due,
      editable: !isInterest,
      submit: (n, reference) =>
        api.post("/sangha-savings/payments", {
          request_id: d.id,
          kind: modal.type,
          amount: n,
          reference,
        }),
    };
  })();

  const waitingContributions = (con?.history ?? []).filter((b) => b.status === "Pending");
  const hasWaiting = pendingPayments.length > 0 || waitingContributions.length > 0;

  return (
    <div className="mp">
      {/* ---------- Header ---------- */}
      <header className="mp-header">
        <span className="mp-header__icon">
          <Wallet size={22} />
        </span>
        <div>
          <h1>My Payments</h1>
          <p>Your daily Sangha contribution, any interest and debt, and every payment you have made.</p>
        </div>
      </header>

      {ovError && <ErrorBox text={ovError} onRetry={load} />}

      {/* ---------- Waiting for admin ---------- */}
      {hasWaiting && (
        <div className="mp-banner" role="status">
          <Clock size={20} />
          <div>
            {waitingContributions.map((b) => (
              <p key={b.batchId}>
                Your <b>{rupees(b.amount)}</b> contribution for {plural(b.days.length, "day")} (ref{" "}
                <b>{b.reference}</b>) is waiting for the admin to confirm.
              </p>
            ))}
            {pendingPayments.map((p) => (
              <p key={p.id}>
                Your <b>{rupees(p.amount)}</b> {p.kind} payment (ref <b>{p.reference}</b>) is waiting for
                the admin to confirm.
              </p>
            ))}
          </div>
        </div>
      )}

      {/* ---------- Summary ---------- */}
      <div className="mp-stats">
        <Stat
          icon={Landmark}
          label="Your Bank Balance"
          value={rupees(member ? member.bankBalance : null)}
          desc="Money in your account"
          tone="green"
          wide
          loading={loading}
        />
        <Stat
          icon={PiggyBank}
          label="Contribution Due"
          value={con ? rupees(con.dueNow) : NA}
          desc="Unpaid days up to today"
          tone={con?.dueNow > 0 ? "red" : undefined}
          loading={loading}
        />
        <Stat
          icon={Percent}
          label="Interest Due"
          value={rupees(member ? member.interestDue : null)}
          desc={hasDebt ? `${rate}% per month` : "No active debt"}
          loading={loading}
        />
        <Stat
          icon={Banknote}
          label="Outstanding Debt"
          value={rupees(member ? member.outstanding : null)}
          desc="Principal you still owe"
          tone={hasDebt ? "red" : undefined}
          loading={loading}
        />
        <Stat
          icon={Wallet}
          label="Contributions Paid"
          value={con ? rupees(con.yearTotal) : NA}
          desc="This year"
          tone="green"
          loading={loading}
        />
      </div>

      {/* ---------- Contribution + debts, and where to pay ---------- */}
      <div className="mp-grid">
        <div className="mp-col">
          <ContributionCard
            con={con}
            loading={loading}
            error={conError}
            onRetry={load}
            selected={selected}
            onToggle={toggleDay}
            onSelectAll={() => setSelected(new Set(payableDates))}
            onClear={() => setSelected(new Set())}
            onPay={() => setModal({ type: "contribution", dates: selectedDates })}
          />

          <Card
            className="mp-debts"
            title="Your Debts"
            subtitle={`Interest is ${rate}% per month on what you still owe`}
          >
            {loading ? (
              <Skel h={150} />
            ) : debts.length === 0 ? (
              <Empty icon={CheckCircle2} text="You have no outstanding debt, so only your daily contribution applies.">
                {onNavigate && (
                  <button type="button" className="mp-btn" onClick={() => onNavigate("savings")}>
                    <HandCoins size={16} /> Sangha Savings
                  </button>
                )}
              </Empty>
            ) : (
              <ul className="mp-debt-list">
                {debts.map((d) => {
                  const repaid =
                    d.approvedAmount > 0
                      ? Math.round(((d.approvedAmount - d.outstanding) / d.approvedAmount) * 100)
                      : 0;
                  const interestWaiting = pendingKinds.has("interest");
                  const principalWaiting = pendingKinds.has("principal");

                  return (
                    <li key={d.id} className="mp-debt">
                      <div className="mp-debt__top">
                        <div>
                          <strong>{rupees(d.outstanding)}</strong>
                          <span>
                            still to repay · {rupees(d.approvedAmount)} taken on {fmtDate(d.disbursedAt)}
                          </span>
                        </div>
                        <Badge tone="blue">Request #{d.id}</Badge>
                      </div>

                      <div className="mp-bar" role="img" aria-label={`${repaid}% repaid`}>
                        <span style={{ width: `${Math.min(Math.max(repaid, 0), 100)}%` }} />
                      </div>
                      <small className="mp-debt__repaid">{repaid}% of the principal repaid</small>

                      <p className="mp-debt__interest">
                        Interest this month: <b>{rupees(d.interest)}</b>
                        <small>
                          {rate}% of {rupees(d.outstanding)} = {rupees(d.monthlyInterest)} a month
                        </small>
                      </p>

                      <div className="mp-btnrow">
                        <button
                          type="button"
                          className="mp-btn mp-btn--primary"
                          disabled={d.interest <= 0 || interestWaiting}
                          onClick={() => setModal({ type: "interest", debt: d })}
                        >
                          {interestWaiting
                            ? "Interest payment pending"
                            : d.interest > 0
                              ? `Pay Interest ${rupees(d.interest)}`
                              : "Interest paid this month"}
                        </button>
                        <button
                          type="button"
                          className="mp-btn"
                          disabled={principalWaiting}
                          onClick={() => setModal({ type: "principal", debt: d })}
                        >
                          {principalWaiting ? "Principal payment pending" : "Pay Principal"}
                        </button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        </div>

        <Card className="mp-payto-card" title="Where to Pay" subtitle="The Sangha Savings Account">
          {loading ? (
            <Skel h={170} />
          ) : !account ? (
            <Empty text="No active Sangha Savings Account." />
          ) : (
            <>
              <div className="mp-acct__head">
                <span className="mp-acct__icon">
                  <Landmark size={18} />
                </span>
                <div>
                  <strong>{sangha?.name}</strong>
                  <small>Code: {sangha?.code}</small>
                </div>
                <Badge tone={account.status === "Active" ? "green" : "orange"}>{account.status}</Badge>
              </div>

              <dl className="mp-kv">
                <KV label="Account Holder" value={account.accountHolder} />
                <KV label="Bank" value={account.bank} />
                <KV label="Account No" value={account.accountNumberMasked} />
                <KV label="IFSC" value={account.ifsc} />
                <KV label="Branch" value={account.branch} />
              </dl>

              <ol className="mp-steps">
                <li>Pay the amount to this account by UPI or bank transfer.</li>
                <li>
                  Tap <b>Pay</b> for your contribution, interest or principal and enter the transaction ID.
                </li>
                <li>Your admin confirms it. Your dues then update and you are notified.</li>
              </ol>
            </>
          )}
        </Card>
      </div>

      {/* ---------- History ---------- */}
      <Card className="mp-history" title="Payment History" subtitle="Everything you have paid or submitted">
        <div className="mp-filters" role="group" aria-label="Filter payments">
          {FILTERS.map((f) => (
            <button
              key={f}
              type="button"
              className={`mp-chip ${filter === f ? "mp-chip--active" : ""}`}
              onClick={() => setFilter(f)}
            >
              {f}
            </button>
          ))}
        </div>

        <label className="mp-field mp-search-field">
          <span>Search</span>
          <div className="mp-search">
            <Search size={16} />
            <input
              type="search"
              placeholder="Search by type or reference"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
        </label>

        {loading ? (
          <Skel h={120} />
        ) : histError ? (
          <ErrorBox text={histError} onRetry={load} />
        ) : filtered.length === 0 ? (
          <Empty text={payments.length === 0 ? "No payments yet." : "No payments match your filters."} />
        ) : (
          <>
            <div className="mp-hrow mp-hrow--head" aria-hidden="true">
              <span>Date</span>
              <span>Type</span>
              <span>Amount</span>
              <span>Reference ID</span>
              <span>Status</span>
              <span>Action</span>
            </div>
            <ul className="mp-hlist">
              {filtered.map((p) => {
                const retry = p.status === "Failed" ? retryTarget(p) : null;
                return (
                  <li key={p.id} className="mp-hrow">
                    <span className="mp-h-date">{fmtDate(p.date)}</span>
                    <strong className="mp-h-type">{p.type}</strong>
                    <strong className="mp-h-amount">{rupees(p.amount)}</strong>
                    <span className="mp-h-ref">{p.ref}</span>
                    <span className="mp-h-status">
                      <Badge tone={STATUS_TONE[p.status] ?? "blue"}>{p.status}</Badge>
                      {p.status === "Failed" && p.reason && <small>{p.reason}</small>}
                    </span>

                    {p.status === "Paid" && (
                      <button type="button" className="mp-link mp-h-action" onClick={() => downloadReceipt(p)}>
                        <Download size={14} /> Receipt
                      </button>
                    )}
                    {p.status === "Pending" && <span className="mp-h-action mp-h-wait">Awaiting admin</span>}
                    {p.status === "Failed" && (
                      <button
                        type="button"
                        className="mp-link mp-h-action"
                        disabled={!retry}
                        onClick={() => retry && setModal(retry)}
                      >
                        Retry <ArrowRight size={14} />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </Card>

      {modalProps && (
        <PayModal
          key={modalProps.key}
          title={modalProps.title}
          subtitle={modalProps.subtitle}
          amount={modalProps.amount}
          max={modalProps.max}
          editable={modalProps.editable}
          account={account}
          submit={modalProps.submit}
          onClose={() => setModal(null)}
          onDone={() => {
            setSelected(new Set());
            load();
          }}
        />
      )}
    </div>
  );
}