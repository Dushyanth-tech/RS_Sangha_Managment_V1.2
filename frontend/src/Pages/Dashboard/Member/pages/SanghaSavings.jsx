import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Landmark,
  Wallet,
  HandCoins,
  ShieldCheck,
  Clock,
  CheckCircle2,
  XCircle,
  ArrowDownLeft,
  ArrowUpRight,
  X,
  Loader2,
  Send,
  Users,
  PiggyBank,
  ClipboardCheck,
  Activity,
  Receipt,
  RefreshCw,
  ArrowRight,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import api from "../../../../api/axiosInstance";
import "./SanghaSavings.css";

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

const errorText = (err, fallback) => {
  if (err?.response?.status === 401) {
    return "Your session has expired. Please log in again.";
  }
  const detail = err?.response?.data?.detail;
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join(", ");
  return (typeof detail === "string" && detail) || fallback;
};

const STATUS_TONE = {
  Pending: "amber",
  "Under Review": "amber",
  Approved: "green",
  Rejected: "red",
  Disbursed: "blue",
  Repaying: "blue",
  Completed: "green",
};

const VERIFY_TONE = {
  Verified: "green",
  "Pending Verification": "amber",
  "Not Verified": "gray",
  Restricted: "red",
};

const STAGES = [
  { key: "Pending", label: "Requested", icon: Send },
  { key: "Under Review", label: "Under Review", icon: ClipboardCheck },
  { key: "Approved", label: "Approved", icon: CheckCircle2 },
  { key: "Disbursed", label: "Disbursed", icon: Wallet },
  { key: "Repaying", label: "Repaying", icon: RefreshCw },
  { key: "Completed", label: "Completed", icon: PiggyBank },
];

const actionLabel = (status) => {
  if (status === "Pending" || status === "Under Review") return "Review";
  if (status === "Approved") return "Disburse";
  if (status === "Disbursed" || status === "Repaying") return "Record Repayment";
  return "View";
};

/* ====================================================================
   SMALL UI PIECES
==================================================================== */

const Badge = ({ tone = "gray", children }) => (
  <span className={`ss-badge ss-badge--${tone}`}>{children}</span>
);

const Skel = ({ w = "100%", h = 18 }) => (
  <span className="ss-skel" style={{ width: w, height: h }} />
);

const Empty = ({ icon: Icon = Receipt, text }) => (
  <div className="ss-empty">
    <Icon size={26} />
    <p>{text}</p>
  </div>
);

const ErrorBox = ({ text, onRetry }) => (
  <div className="ss-error" role="alert">
    <span>{text}</span>
    {onRetry && (
      <button type="button" onClick={onRetry}>
        Retry
      </button>
    )}
  </div>
);

const Section = ({ id, title, subtitle, action, children }) => (
  <section id={id} className="ss-section">
    <div className="ss-section__head">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {action}
    </div>
    {children}
  </section>
);

function useModalBehavior(onClose) {
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
}

function Modal({ title, subtitle, onClose, wide, children }) {
  useModalBehavior(onClose);
  return (
    <div
      className="ss-overlay"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        className={`ss-modal ${wide ? "ss-modal--wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header className="ss-modal__head">
          <div>
            <h3>{title}</h3>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button
            type="button"
            className="ss-icon-btn"
            onClick={onClose}
            aria-label="Close"
          >
            <X size={18} />
          </button>
        </header>
        <div className="ss-modal__body">{children}</div>
      </div>
    </div>
  );
}

/* ====================================================================
   FINANCIAL SNAPSHOT
==================================================================== */

function Stat({ icon: Icon, label, value, desc, tone = "blue", loading }) {
  return (
    <article className="ss-stat">
      <div className={`ss-stat__icon ss-tone-${tone}`}>
        <Icon size={18} />
      </div>
      <div className="ss-stat__body">
        <span className="ss-stat__label">{label}</span>
        {loading ? <Skel w="70%" h={26} /> : <strong className="ss-stat__value">{value}</strong>}
        {loading ? <Skel w="50%" h={12} /> : <span className="ss-stat__desc">{desc}</span>}
      </div>
    </article>
  );
}

function Snapshot({ isStaff, ov, loading }) {
  const fund = ov?.fund;
  const member = ov?.member;
  const account = ov?.account;

  let fundValue = NA;
  let fundDesc = "Available in Sangha Savings";
  if (ov) {
    if (!ov.sangha) {
      fundValue = "No Sangha";
      fundDesc = "You are not assigned to a Sangha";
    } else if (!account) {
      fundValue = "No Account";
      fundDesc = "No active Sangha Savings Account";
    } else {
      fundValue = rupees(fund?.balance);
    }
  }

  const verification = member?.verificationStatus;
  const verifyDesc = {
    Verified: "Eligible for requests",
    "Pending Verification": "Verification under review",
    "Not Verified": "Verify to request money",
    Restricted: "Account access is restricted",
  }[verification];

  return (
    <div className="ss-stats">
      <Stat
        icon={Landmark}
        label="Sangha Fund Balance"
        value={fundValue}
        desc={fundDesc}
        loading={loading}
      />

      {isStaff ? (
        <>
          <Stat
            icon={Users}
            label="Money With Members"
            value={rupees(fund?.withMembers)}
            desc="Still to be repaid"
            loading={loading}
          />
          <Stat
            icon={Clock}
            label="Pending Requests"
            value={fund?.pendingRequests ?? 0}
            desc="Awaiting review"
            tone="amber"
            loading={loading}
          />
          <Stat
            icon={ShieldCheck}
            label="Savings Account"
            value={account ? account.status : "Not Created"}
            desc={account ? "Sangha Savings Account" : "No active account"}
            tone={account?.status === "Active" ? "green" : "gray"}
            loading={loading}
          />
        </>
      ) : (
        <>
          <Stat
            icon={HandCoins}
            label="My Outstanding"
            value={rupees(member?.outstanding ?? 0)}
            desc="Amount remaining to repay"
            tone={member?.outstanding > 0 ? "red" : "gray"}
            loading={loading}
          />
          <Stat
            icon={ShieldCheck}
            label="Account Status"
            value={verification ?? NA}
            desc={verifyDesc ?? ""}
            tone={VERIFY_TONE[verification] ?? "gray"}
            loading={loading}
          />
        </>
      )}
    </div>
  );
}

/* ====================================================================
   TRUST PROFILE
==================================================================== */

function TrustProfile({ trust, loading }) {
  const items = [
    ["Monthly Salary", trust?.monthlySalary != null ? rupees(trust.monthlySalary) : NA],
    ["Previous Requests", trust ? trust.previousRequests : NA],
    ["Completed Requests", trust ? trust.completedRequests : NA],
    [
      "Repayment Consistency",
      trust?.repaymentConsistency != null ? `${trust.repaymentConsistency}%` : NA,
    ],
    ["Current Outstanding", trust ? rupees(trust.currentOutstanding) : NA],
    ["Last Repayment", trust?.lastRepayment ? fmtDate(trust.lastRepayment) : NA],
  ];

  return (
    <Section
      id="ss-trust"
      title="Trust Profile"
      subtitle="Your history with Sangha Savings"
    >
      <dl className="ss-trust">
        {items.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{loading ? <Skel w="60%" h={16} /> : value}</dd>
          </div>
        ))}
      </dl>
      <p className="ss-footnote">
        This is your Sangha repayment history only. It is not a CIBIL or credit
        bureau score, and it never approves a request automatically. The
        Admin/Superadmin makes the final decision.
      </p>
    </Section>
  );
}

/* ====================================================================
   EMERGENCY REQUEST CTA
==================================================================== */

function EmergencyCta({ eligibility, loading, onRequest, onOpenAccountStatus, onNavigate }) {
  const reasons = eligibility?.reasons ?? [];
  const canRequest = !!eligibility?.canRequest;

  const reasonAction = (code) => {
    if (code === "not_verified" && onOpenAccountStatus) {
      return { label: "View Account Status", run: onOpenAccountStatus };
    }
    if (code === "profile_incomplete" && onNavigate) {
      return { label: "Complete Profile", run: () => onNavigate("profile") };
    }
    return null;
  };

  return (
    <Section id="ss-request" title="Need Financial Support?">
      <p className="ss-cta__text">
        Request emergency money from your Sangha Savings Account.
      </p>

      {loading ? (
        <Skel h={44} />
      ) : (
        <>
          {reasons.length > 0 && (
            <ul className="ss-reasons">
              {reasons.map((r) => {
                const action = reasonAction(r.code);
                return (
                  <li key={r.code}>
                    <span>{r.message}</span>
                    {action && (
                      <button type="button" onClick={action.run}>
                        {action.label} <ArrowRight size={13} />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          <button
            type="button"
            className="ss-btn ss-btn--primary ss-btn--block"
            onClick={onRequest}
            disabled={!canRequest}
          >
            <HandCoins size={18} />
            Request Emergency Money
          </button>
        </>
      )}
    </Section>
  );
}

/* ====================================================================
   MONEY JOURNEY
==================================================================== */

function MoneyJourney({ request, isStaff }) {
  const status = request?.status;
  const rejected = status === "Rejected";
  const current = rejected ? 2 : STAGES.findIndex((s) => s.key === status);

  const stateFor = (i) => {
    if (!request) return "idle";
    if (rejected) return i < 2 ? "done" : i === 2 ? "rejected" : "idle";
    if (i < current) return "done";
    if (i === current) return status === "Completed" ? "done" : "current";
    return "idle";
  };

  const detail = (key) => {
    if (!request) return "";
    if (key === "Pending") return rupees(request.amount);
    if (key === "Approved") return request.approvedAmount != null ? rupees(request.approvedAmount) : "";
    if (key === "Disbursed") return request.approvedAmount != null && current >= 3 ? rupees(request.approvedAmount) : "";
    if (key === "Repaying") return current >= 4 ? `Outstanding ${rupees(request.outstanding)}` : "";
    return "";
  };

  const nodes = [
    { label: "Sangha Savings", icon: Landmark, sub: "Fund", state: request ? "done" : "idle" },
    ...STAGES.map((s, i) => ({
      label: rejected && i === 2 ? "Rejected" : s.label,
      icon: rejected && i === 2 ? XCircle : s.icon,
      sub: rejected && i === 2 ? "" : detail(s.key),
      state: stateFor(i),
    })),
    {
      label: "Returned to Sangha",
      icon: ArrowDownLeft,
      sub: "",
      state: status === "Completed" ? "done" : "idle",
    },
  ];

  return (
    <Section
      id="ss-journey"
      title="The Money Journey"
      subtitle={
        isStaff
          ? "How every emergency request moves through the Sangha"
          : request
            ? `Your latest request: #${request.id}`
            : "Follow your request from the Sangha fund and back"
      }
    >
      <ol className="ss-journey">
        {nodes.map((n, i) => {
          const Icon = n.icon;
          return (
            <li key={`${n.label}-${i}`} className={`ss-node ss-node--${n.state}`}>
              <span className="ss-node__icon">
                <Icon size={18} />
              </span>
              <span className="ss-node__label">{n.label}</span>
              {n.sub && <span className="ss-node__sub">{n.sub}</span>}
            </li>
          );
        })}
      </ol>
    </Section>
  );
}

/* ====================================================================
   MEMBER FINANCIAL POSITION
==================================================================== */

function FinancialPosition({ member, loading }) {
  const month = new Date().toLocaleDateString("en-IN", { month: "long", year: "numeric" });

  const rows = [
    ["Current Month", month],
    ["Contribution", NA],
    ["Money Received (this month)", rupees(member?.receivedThisMonth)],
    ["Total Received", rupees(member?.totalReceived)],
    ["Total Repaid", rupees(member?.totalRepaid)],
    ["Total Interest Paid", rupees(member?.totalInterestPaid)],
  ];

  return (
    <Section
      id="ss-position"
      title="My Financial Position"
      subtitle="What you still owe"
    >
      <div className="ss-pos">
        <div className="ss-pos__box ss-pos__box--red">
          <span>Outstanding Amount</span>
          {loading ? <Skel w="60%" h={26} /> : <strong>{rupees(member?.outstanding ?? 0)}</strong>}
          <small>Money you still need to repay</small>
        </div>
      </div>

      <dl className="ss-kv">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{loading ? <Skel w="50%" h={14} /> : value}</dd>
          </div>
        ))}
      </dl>
    </Section>
  );
}

function AvailableBalanceHistory({ items, loading, error, snapshotError, onRetry }) {
  const chartItems = items.map((item) => ({
    ...item,
    chartBalance: Number(item.balance),
  }));

  return (
    <Section
      id="ss-available-balance-history"
      title="Bank Balance History"
      subtitle="Your bank balance, updated whenever money is credited or debited"
    >
      {snapshotError && <ErrorBox text={snapshotError} onRetry={onRetry} />}
      {loading ? (
        <Skel h={100} />
      ) : error ? (
        <ErrorBox text={error} onRetry={onRetry} />
      ) : items.length === 0 ? (
        <Empty icon={Wallet} text="No bank balance has been recorded yet." />
      ) : (
        <>
          {chartItems.length > 1 && (
            <div className="ss-balance-chart">
              <ResponsiveContainer width="100%" height={240}>
                <LineChart
                  data={chartItems}
                  margin={{ top: 12, right: 16, bottom: 8, left: 8 }}
                >
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    dataKey="recorded_at"
                    tickFormatter={fmtDate}
                  />
                  <YAxis
                    tickFormatter={(value) =>
                      `₹${Number(value).toLocaleString("en-IN")}`
                    }
                    width={82}
                  />
                  <Tooltip
                    labelFormatter={(value) =>
                      new Date(value).toLocaleString("en-IN", {
                        dateStyle: "medium",
                        timeStyle: "short",
                      })
                    }
                    formatter={(value) => [rupees(value), "Bank Balance"]}
                  />
                  <Line
                    type="linear"
                    dataKey="chartBalance"
                    name="Available balance"
                    stroke="#1a7a51"
                    strokeWidth={2}
                    dot={{ r: 4 }}
                    activeDot={{ r: 6 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="ss-balance-history">
            <table>
              <thead>
                <tr>
                  <th scope="col">Recorded</th>
                  <th scope="col">Bank Balance</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>{fmtDate(item.recorded_at)}</td>
                    <td>{rupees(item.balance)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </Section>
  );
}

/* ====================================================================
   SAVINGS ACCOUNT INFO
==================================================================== */

function SavingsAccountCard({ sangha, account, loading }) {
  const rows = account
    ? [
        ["Sangha", sangha ? `${sangha.name} (${sangha.code})` : "—"],
        ["Bank Name", account.bank],
        ["Account Holder", account.accountHolder],
        ["Account Number", account.accountNumberMasked],
        ["IFSC", account.ifsc],
        ["Branch", account.branch],
        ["Account Type", account.accountType],
      ]
    : [];

  return (
    <Section id="ss-account" title="Sangha Savings Account">
      {loading ? (
        <Skel h={120} />
      ) : !account ? (
        <Empty icon={Landmark} text="No active Sangha Savings Account." />
      ) : (
        <>
          <dl className="ss-kv">
            {rows.map(([label, value]) => (
              <div key={label}>
                <dt>{label}</dt>
                <dd>{value || "—"}</dd>
              </div>
            ))}
            <div>
              <dt>Status</dt>
              <dd>
                <Badge tone={account.status === "Active" ? "green" : "gray"}>{account.status}</Badge>
              </dd>
            </div>
          </dl>
        </>
      )}
    </Section>
  );
}

/* ====================================================================
   REQUEST HISTORY
==================================================================== */

function RequestHistory({ id, title, subtitle, requests, loading, error, onRetry, showMember, isStaff, onOpen }) {
  return (
    <Section id={id} title={title} subtitle={subtitle}>
      {loading ? (
        <Skel h={110} />
      ) : error ? (
        <ErrorBox text={error} onRetry={onRetry} />
      ) : requests.length === 0 ? (
        <Empty icon={HandCoins} text="No emergency money requests yet." />
      ) : (
        <ol className="ss-timeline">
          {requests.map((r) => (
            <li key={r.id} className={`ss-tl-item ss-tl-item--${STATUS_TONE[r.status] ?? "gray"}`}>
              <span className="ss-tl-dot" />
              <div className="ss-tl-card">
                <div className="ss-tl-top">
                  <div>
                    <strong className="ss-tl-amount">{rupees(r.amount)}</strong>
                    <span className="ss-tl-reason">{r.reason}</span>
                  </div>
                  <Badge tone={STATUS_TONE[r.status] ?? "gray"}>{r.status}</Badge>
                </div>

                <dl className="ss-tl-meta">
                  <div>
                    <dt>Request ID</dt>
                    <dd>#{r.id}</dd>
                  </div>
                  <div>
                    <dt>Date</dt>
                    <dd>{fmtDate(r.requestedAt)}</dd>
                  </div>
                  {showMember && (
                    <div>
                      <dt>Member</dt>
                      <dd>{r.memberName}</dd>
                    </div>
                  )}
                  <div>
                    <dt>Approved</dt>
                    <dd>{r.approvedAmount != null ? rupees(r.approvedAmount) : "—"}</dd>
                  </div>
                  <div>
                    <dt>Outstanding</dt>
                    <dd>{r.outstanding > 0 ? rupees(r.outstanding) : "—"}</dd>
                  </div>
                  {r.reviewer && (
                    <div>
                      <dt>Reviewer</dt>
                      <dd>{r.reviewer}</dd>
                    </div>
                  )}
                  {r.rejectionReason && (
                    <div className="ss-wide">
                      <dt>Rejection reason</dt>
                      <dd>{r.rejectionReason}</dd>
                    </div>
                  )}
                </dl>

                {isStaff && (
                  <button type="button" className="ss-btn ss-btn--soft" onClick={() => onOpen(r.id)}>
                    {actionLabel(r.status)} <ArrowRight size={14} />
                  </button>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

/* ====================================================================
   REPAYMENTS + TRANSACTIONS
==================================================================== */

function RepaymentHistory({ items, loading, error, onRetry, showMember }) {
  return (
    <Section id="ss-repayments" title="Repayment History" subtitle="Principal and interest returned to the Sangha">
      {loading ? (
        <Skel h={90} />
      ) : error ? (
        <ErrorBox text={error} onRetry={onRetry} />
      ) : items.length === 0 ? (
        <Empty icon={RefreshCw} text="No repayment history yet." />
      ) : (
        <ul className="ss-list">
          {items.map((p) => (
            <li key={p.id} className="ss-row">
              <div className="ss-cell ss-cell--main" data-label="Date">
                <strong>{fmtDate(p.paidAt)}</strong>
                {showMember && <small>{p.memberName}</small>}
              </div>
              <div className="ss-cell" data-label="Amount Paid">
                <b>{rupees(p.amount)}</b>
              </div>
              <div className="ss-cell" data-label="Principal">{rupees(p.principal)}</div>
              <div className="ss-cell" data-label="Interest">{rupees(p.interest)}</div>
              <div className="ss-cell" data-label="Remaining">{rupees(p.remaining)}</div>
              <div className="ss-cell" data-label="Status">
                <Badge tone="green">{p.status}</Badge>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function TransactionHistory({ items, loading, error, onRetry, showMember }) {
  return (
    <Section id="ss-transactions" title="Transaction History" subtitle="Money movement in Sangha Savings only">
      {loading ? (
        <Skel h={90} />
      ) : error ? (
        <ErrorBox text={error} onRetry={onRetry} />
      ) : items.length === 0 ? (
        <Empty icon={Receipt} text="No transactions yet." />
      ) : (
        <ul className="ss-list">
          {items.map((t) => {
            const received = t.direction === "Received";
            return (
              <li key={t.id} className="ss-row ss-row--txn">
                <div className="ss-cell ss-cell--main" data-label="Date">
                  <strong>{fmtDate(t.date)}</strong>
                  {showMember && <small>{t.memberName}</small>}
                </div>
                <div className="ss-cell" data-label="Type">{t.type}</div>
                <div className={`ss-cell ss-amount ${received ? "ss-amount--in" : "ss-amount--out"}`} data-label="Amount">
                  {received ? <ArrowDownLeft size={14} /> : <ArrowUpRight size={14} />}
                  {received ? "+" : "-"}
                  {rupees(t.amount)}
                </div>
                <div className="ss-cell" data-label="Direction">
                  <Badge tone={received ? "green" : "blue"}>{t.direction}</Badge>
                </div>
                <div className="ss-cell" data-label="Status">
                  <Badge tone="green">{t.status}</Badge>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Section>
  );
}

/* ====================================================================
   FUND HEALTH (admin / superadmin)
==================================================================== */

function FundHealth({ fund, loading }) {
  const tiles = [
    ["Total Sangha Fund", rupees(fund?.total)],
    ["Money With Members", rupees(fund?.withMembers)],
    ["Available Fund", rupees(fund?.balance)],
    ["Pending Requests", fund?.pendingRequests ?? 0],
    ["Monthly Money Given", rupees(fund?.monthlyGiven)],
    ["Monthly Money Returned", rupees(fund?.monthlyReturned)],
    ["Interest Returned", rupees(fund?.interestReturned)],
    ["Active Member Accounts", fund?.activeAccounts ?? 0],
  ];
  const utilization = Math.min(Number(fund?.utilization ?? 0), 100);

  return (
    <Section id="ss-health" title="Fund Health" subtitle="How the Sangha fund is being used">
      {loading ? (
        <Skel h={140} />
      ) : !fund ? (
        <Empty icon={Activity} text="No active Sangha Savings Account." />
      ) : (
        <>
          <div className="ss-util">
            <div className="ss-util__top">
              <span>Fund Utilization</span>
              <strong>{utilization}%</strong>
            </div>
            <div className="ss-bar">
              <span style={{ width: `${utilization}%` }} />
            </div>
          </div>
          <div className="ss-health">
            {tiles.map(([label, value]) => (
              <div key={label} className="ss-health__tile">
                <span>{label}</span>
                <strong>{value}</strong>
              </div>
            ))}
          </div>
        </>
      )}
    </Section>
  );
}

/* ====================================================================
   QUICK ACTIONS
==================================================================== */

function QuickActions({ actions }) {
  return (
    <Section id="ss-quick" title="Quick Actions">
      <div className="ss-quick">
        {actions.map(({ label, icon: Icon, run, disabled }) => (
          <button key={label} type="button" className="ss-quick__btn" onClick={run} disabled={disabled}>
            <Icon size={18} />
            {label}
          </button>
        ))}
      </div>
    </Section>
  );
}

/* ====================================================================
   REQUEST MODAL (member)
==================================================================== */


function RequestModal({ ov, onClose, onSubmitted }) {
  const member = ov.member;
  const fund = ov.fund;

  const [step, setStep] = useState("form");
  const [form, setForm] = useState({
    amount: "",
    reason: "",
  });

  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [snapshots, setSnapshots] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");

  const lock = useRef(false);

  const amount = Number(form.amount);

  // Load the member's existing history. No snapshot is created here.
  useEffect(() => {
    let active = true;

    async function loadHistory() {
      setHistoryLoading(true);
      setHistoryError("");

      try {
        const response = await api.get("/me/bank-balance/history", {
          params: { days: 28 },
        });

        if (!Array.isArray(response.data)) {
          throw new Error("Unexpected balance history response.");
        }

        if (active) {
          setSnapshots(
            response.data.filter((item) => {
              const balance = Number(item.balance);
              return (
                Number.isFinite(balance) &&
                balance >= 0 &&
                item.recorded_at &&
                !Number.isNaN(Date.parse(item.recorded_at))
              );
            })
          );
        }
      } catch (err) {
        if (active) {
          setHistoryError(
            err.response?.data?.detail ||
              "Unable to load your available-balance history."
          );
        }
      } finally {
        if (active) setHistoryLoading(false);
      }
    }

    loadHistory();

    return () => {
      active = false;
    };
  }, []);

  const assessment = useMemo(() => {
    const sorted = [...snapshots].sort(
      (a, b) =>
        new Date(a.recorded_at).getTime() -
        new Date(b.recorded_at).getTime()
    );

    const values = sorted.map((item) => Number(item.balance));

    if (!values.length) {
      return {
        count: 0,
        average: null,
        minimum: null,
        maximum: null,
        trend: "Not enough history",
        change: null,
      };
    }

    const first = values[0];
    const latest = values[values.length - 1];
    const difference = latest - first;

    let trend = "Not enough history";

    if (values.length >= 2) {
      const tolerance = 0.01;

      if (difference > tolerance) trend = "Increasing";
      else if (difference < -tolerance) trend = "Decreasing";
      else trend = "Stable";
    }

    return {
      count: values.length,
      average:
        values.reduce((sum, value) => sum + value, 0) / values.length,
      minimum: Math.min(...values),
      maximum: Math.max(...values),
      trend,
      change: values.length >= 2 ? difference : null,
    };
  }, [snapshots]);

  const update = (event) => {
    const { name, value } = event.target;

    setForm((previous) => ({
      ...previous,
      [name]: value,
    }));

    setError("");
  };

  const validate = () => {
    if (
      !member?.profile?.fullname ||
      !member?.profile?.phone ||
      !member?.profile?.address
    ) {
      return "Your name, phone number and address must be in your profile.";
    }

    if (ov.eligibility && !ov.eligibility.canRequest) {
      return (
        ov.eligibility.reasons?.[0]?.message ||
        "You are currently not eligible to request emergency money."
      );
    }

    if (!Number.isFinite(amount) || amount <= 0) {
      return "Enter a requested amount greater than ₹0.";
    }

    if (amount > Number(fund?.balance ?? 0)) {
      return "Requested amount exceeds the available Sangha fund.";
    }

    if (form.reason.trim().length < 10) {
      return "Please explain your reason using at least 10 characters.";
    }

    return "";
  };

  const goConfirm = () => {
    const problem = validate();

    if (problem) {
      setError(problem);
      return;
    }

    setError("");
    setStep("confirm");
  };

  const submit = async () => {
    if (lock.current) return;

    const problem = validate();

    if (problem) {
      setError(problem);
      setStep("form");
      return;
    }

    lock.current = true;
    setSubmitting(true);
    setError("");

    try {
      // The backend rechecks member eligibility and the current
      // Sangha fund balance before saving the request.
      const response = await api.post("/sangha-savings/requests", {
        amount,
        reason: form.reason.trim(),
      });

      setResult(response.data.request);
      setStep("done");
      onSubmitted();
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          err.message ||
          "Unable to submit the request."
      );
      lock.current = false;
    } finally {
      setSubmitting(false);
    }
  };

  const formatTrend = () => {
    if (assessment.change === null) {
      return assessment.trend;
    }

    const sign = assessment.change > 0 ? "+" : "";

    return `${assessment.trend} (${sign}${rupees(
      assessment.change
    )})`;
  };

  return (
    <Modal
      title="Request Emergency Money"
      subtitle="From your Sangha Savings Account"
      onClose={onClose}
    >
      {step === "form" && (
        <div className="ss-form">
          <label>
            Name
            <input value={member?.profile?.fullname || ""} readOnly />
          </label>

          <label>
            Phone Number
            <input value={member?.profile?.phone || ""} readOnly />
          </label>

          <label className="ss-wide">
            Address
            <input value={member?.profile?.address || ""} readOnly />
          </label>

          <label>
            Money Requested (₹)
            <input
              name="amount"
              type="number"
              inputMode="decimal"
              min="0.01"
              step="0.01"
              max={fund?.balance ?? 0}
              placeholder="Enter amount"
              value={form.amount}
              onChange={update}
            />
          </label>

          <label className="ss-wide">
            Reason for Request
            <textarea
              name="reason"
              rows={4}
              maxLength={500}
              placeholder="Explain why you need the money..."
              value={form.reason}
              onChange={update}
            />
          </label>

          <div className="ss-assessment ss-wide">
            <div className="ss-assessment__heading">
              <div>
                <h4>Available-Balance Assessment</h4>
                <p>Saved history from the last 28 days</p>
              </div>

              <span className="ss-assessment__badge">
                {historyLoading ? "Loading" : `${assessment.count} records`}
              </span>
            </div>

            {historyLoading ? (
              <p className="ss-assessment__message">
                Loading your saved balance history...
              </p>
            ) : historyError ? (
              <div className="ss-assessment__message ss-assessment__message--error">
                {historyError}
              </div>
            ) : assessment.count === 0 ? (
              <div className="ss-assessment__message">
                No saved balance history was found for this period.
                Historical analysis is unavailable, but the existing
                eligibility and fund-balance checks still apply.
              </div>
            ) : (
              <div className="ss-assessment__grid">
                <div className="ss-assessment__item">
                  <span>Average balance</span>
                  <strong>{rupees(assessment.average)}</strong>
                </div>

                <div className="ss-assessment__item">
                  <span>Lowest balance</span>
                  <strong>{rupees(assessment.minimum)}</strong>
                </div>

                <div className="ss-assessment__item">
                  <span>Highest balance</span>
                  <strong>{rupees(assessment.maximum)}</strong>
                </div>

                <div className="ss-assessment__item">
                  <span>Balance trend</span>
                  <strong>{formatTrend()}</strong>
                </div>
              </div>
            )}

            <p className="ss-assessment__disclaimer">
              This is application-calculated balance history, not a live
              personal bank balance. It is supporting information only;
              the administrator makes the final decision.
            </p>
          </div>

          <p className="ss-note ss-wide">
            Available Sangha fund:{" "}
            <strong>{rupees(fund?.balance ?? 0)}</strong>
          </p>

          {(member?.outstanding ?? 0) > 0 && (
            <p className="ss-note ss-note--warn ss-wide">
              Your current outstanding amount is{" "}
              <strong>{rupees(member.outstanding)}</strong>. Your repayment
              history may be reviewed by the administrator.
            </p>
          )}

          {error && <div className="ss-alert ss-wide">{error}</div>}

          <div className="ss-actions ss-wide">
            <button
              type="button"
              className="ss-btn"
              onClick={onClose}
            >
              Cancel
            </button>

            <button
              type="button"
              className="ss-btn ss-btn--primary"
              onClick={goConfirm}
            >
              Continue
            </button>
          </div>
        </div>
      )}

      {step === "confirm" && (
        <>
          <h4 className="ss-summary-title">Review Your Request</h4>

          <dl className="ss-kv">
            <div>
              <dt>Requested Amount</dt>
              <dd>{rupees(amount)}</dd>
            </div>

            <div>
              <dt>Available Sangha Fund</dt>
              <dd>{rupees(fund?.balance ?? 0)}</dd>
            </div>

            <div>
              <dt>Balance History</dt>
              <dd>
                {historyLoading
                  ? "Loading..."
                  : `${assessment.count} saved records`}
              </dd>
            </div>

            <div className="ss-wide">
              <dt>Reason</dt>
              <dd>{form.reason.trim()}</dd>
            </div>
          </dl>

          <p className="ss-assessment__disclaimer">
            Your request is not approved automatically. The backend checks
            eligibility and available funds again when you submit.
          </p>

          {error && <div className="ss-alert">{error}</div>}

          <div className="ss-actions">
            <button
              type="button"
              className="ss-btn"
              onClick={() => {
                setError("");
                setStep("form");
              }}
              disabled={submitting}
            >
              Back
            </button>

            <button
              type="button"
              className="ss-btn ss-btn--primary"
              onClick={submit}
              disabled={submitting}
            >
              {submitting ? (
                <>
                  <Loader2 size={16} className="ss-spin" />
                  Submitting...
                </>
              ) : (
                "Submit Request"
              )}
            </button>
          </div>
        </>
      )}

      {step === "done" && result && (
        <div className="ss-success">
          <CheckCircle2 size={40} />
          <h4>Request Submitted Successfully</h4>

          <dl className="ss-kv">
            <div>
              <dt>Request ID</dt>
              <dd>#{result.id}</dd>
            </div>

            <div>
              <dt>Requested Amount</dt>
              <dd>{rupees(result.amount)}</dd>
            </div>

            <div>
              <dt>Status</dt>
              <dd>
                <Badge tone="amber">Pending Review</Badge>
              </dd>
            </div>

            <div>
              <dt>Submitted</dt>
              <dd>{fmtDate(result.requestedAt)}</dd>
            </div>
          </dl>

          <button
            type="button"
            className="ss-btn ss-btn--primary"
            onClick={onClose}
          >
            Done
          </button>
        </div>
      )}
    </Modal>
  );
}

/* ====================================================================
   REVIEW MODAL (admin / superadmin)
==================================================================== */

function ReviewModal({ id, onClose, onChanged }) {
  const [d, setD] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [mode, setMode] = useState(null); // null | approve | reject
  const [approveAmount, setApproveAmount] = useState("");
  const [rejectReason, setRejectReason] = useState("");
  const [rep, setRep] = useState({ principal: "", interest: "0", onTime: true });

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError("");
      const res = await api.get(`/sangha-savings/requests/${id}`);
      setD(res.data);
      setApproveAmount(String(res.data.amount));
    } catch (err) {
      console.error("Error loading request:", err);
      setError(errorText(err, "Unable to load this request."));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const run = async (fn) => {
    setBusy(true);
    setActionError("");
    try {
      await fn();
      setMode(null);
      await load();
      onChanged();
    } catch (err) {
      console.error("Review action failed:", err);
      setActionError(errorText(err, "Unable to complete this action."));
    } finally {
      setBusy(false);
    }
  };

  const review = (body) => run(() => api.patch(`/sangha-savings/requests/${id}/review`, body));
  const disburse = () => run(() => api.post(`/sangha-savings/requests/${id}/disburse`, {}));
  const repay = () =>
    run(() =>
      api.post(`/sangha-savings/requests/${id}/repayments`, {
        principal: Number(rep.principal || 0),
        interest: Number(rep.interest || 0),
        is_on_time: rep.onTime,
      }),
    );

  const status = d?.status;
  const decidable = status === "Pending" || status === "Under Review";
  const verified = d?.verification === "Verified";

  return (
    <Modal
      wide
      title={d ? `Request #${d.id}` : "Request"}
      subtitle={d ? `${d.memberName} · ${d.sangha.name}` : ""}
      onClose={onClose}
    >
      {loading && !d ? (
        <Skel h={200} />
      ) : error ? (
        <ErrorBox text={error} onRetry={load} />
      ) : d ? (
        <>
          <div className="ss-review-head">
            <Badge tone={STATUS_TONE[status] ?? "gray"}>{status}</Badge>
            <Badge tone={VERIFY_TONE[d.verification] ?? "gray"}>{d.verification}</Badge>
          </div>

          <dl className="ss-kv ss-kv--2">
            <div><dt>Member Name</dt><dd>{d.memberName}</dd></div>
            <div><dt>Phone</dt><dd>{d.phone || "—"}</dd></div>
            <div><dt>Sangha</dt><dd>{d.sangha.name} ({d.sangha.code})</dd></div>
            <div><dt>Requested Amount</dt><dd>{rupees(d.amount)}</dd></div>
            <div><dt>Monthly Salary</dt><dd>{rupees(d.monthlySalary)}</dd></div>
            <div><dt>Available Sangha Fund</dt><dd>{rupees(d.availableFund)}</dd></div>
            <div><dt>Previous Requests</dt><dd>{d.previousRequests}</dd></div>
            <div><dt>Completed Requests</dt><dd>{d.completedRequests}</dd></div>
            <div><dt>Current Outstanding</dt><dd>{rupees(d.currentOutstanding)}</dd></div>
            <div>
              <dt>Repayment Consistency</dt>
              <dd>{d.repaymentConsistency != null ? `${d.repaymentConsistency}%` : NA}</dd>
            </div>
            <div className="ss-wide"><dt>Reason</dt><dd>{d.reason}</dd></div>
            {d.rejectionReason && (
              <div className="ss-wide"><dt>Rejection reason</dt><dd>{d.rejectionReason}</dd></div>
            )}
          </dl>

          <h4 className="ss-summary-title">Previous Repayment History</h4>
          {d.repayments.length === 0 ? (
            <Empty icon={RefreshCw} text="No repayment history yet." />
          ) : (
            <ul className="ss-mini">
              {d.repayments.map((p, i) => (
                <li key={`${p.paidAt}-${i}`}>
                  <span>{fmtDate(p.paidAt)}</span>
                  <span>
                    {rupees(p.principal)} + {rupees(p.interest)} interest
                  </span>
                  <Badge tone={p.isOnTime ? "green" : "amber"}>{p.isOnTime ? "On time" : "Late"}</Badge>
                </li>
              ))}
            </ul>
          )}

          <p className="ss-footnote">
            Repayment consistency is Sangha history only. Approval is your decision.
          </p>

          {actionError && <div className="ss-alert">{actionError}</div>}

          {/* ----- actions by status ----- */}
          {decidable && mode === null && (
            <div className="ss-actions">
              {status === "Pending" && (
                <button
                  type="button"
                  className="ss-btn"
                  disabled={busy}
                  onClick={() => review({ action: "start_review" })}
                >
                  Start Review
                </button>
              )}
              <button type="button" className="ss-btn ss-btn--danger" disabled={busy} onClick={() => setMode("reject")}>
                Reject
              </button>
              <button
                type="button"
                className="ss-btn ss-btn--primary"
                disabled={busy || !verified}
                onClick={() => setMode("approve")}
                title={verified ? "" : "The member must be verified first"}
              >
                Approve
              </button>
            </div>
          )}

          {decidable && !verified && mode === null && (
            <p className="ss-note ss-note--warn">The member must be verified before approval.</p>
          )}

          {mode === "approve" && (
            <div className="ss-inline">
              <label>
                Approved amount (₹)
                <input
                  type="number"
                  min="1"
                  max={d.amount}
                  value={approveAmount}
                  onChange={(e) => setApproveAmount(e.target.value)}
                />
              </label>
              <div className="ss-actions">
                <button type="button" className="ss-btn" disabled={busy} onClick={() => setMode(null)}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="ss-btn ss-btn--primary"
                  disabled={busy || !(Number(approveAmount) > 0)}
                  onClick={() => review({ action: "approve", approved_amount: Number(approveAmount) })}
                >
                  {busy ? <Loader2 size={16} className="ss-spin" /> : "Confirm Approval"}
                </button>
              </div>
            </div>
          )}

          {mode === "reject" && (
            <div className="ss-inline">
              <label>
                Reason for rejection
                <textarea
                  rows={3}
                  maxLength={255}
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                />
              </label>
              <div className="ss-actions">
                <button type="button" className="ss-btn" disabled={busy} onClick={() => setMode(null)}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="ss-btn ss-btn--danger"
                  disabled={busy || !rejectReason.trim()}
                  onClick={() => review({ action: "reject", reason: rejectReason.trim() })}
                >
                  {busy ? <Loader2 size={16} className="ss-spin" /> : "Confirm Rejection"}
                </button>
              </div>
            </div>
          )}

          {status === "Approved" && (
            <div className="ss-inline">
              <p className="ss-note">
                Approved for <strong>{rupees(d.approvedAmount)}</strong>. Disbursing records that the
                money was given to the member and deducts it from the Sangha fund.
              </p>
              <div className="ss-actions">
                <button type="button" className="ss-btn ss-btn--primary" disabled={busy} onClick={disburse}>
                  {busy ? <Loader2 size={16} className="ss-spin" /> : "Mark as Disbursed"}
                </button>
              </div>
            </div>
          )}

          {(status === "Disbursed" || status === "Repaying") && (
            <div className="ss-inline">
              <p className="ss-note">
                Outstanding on this request: <strong>{rupees(d.requestOutstanding)}</strong>
              </p>
              <div className="ss-form">
                <label>
                  Principal paid (₹)
                  <input
                    type="number"
                    min="0"
                    value={rep.principal}
                    onChange={(e) => setRep((p) => ({ ...p, principal: e.target.value }))}
                  />
                </label>
                <label>
                  Interest paid (₹)
                  <input
                    type="number"
                    min="0"
                    value={rep.interest}
                    onChange={(e) => setRep((p) => ({ ...p, interest: e.target.value }))}
                  />
                </label>
                <label className="ss-check ss-wide">
                  <input
                    type="checkbox"
                    checked={rep.onTime}
                    onChange={(e) => setRep((p) => ({ ...p, onTime: e.target.checked }))}
                  />
                  Paid on time
                </label>
              </div>
              <div className="ss-actions">
                <button
                  type="button"
                  className="ss-btn ss-btn--primary"
                  disabled={busy || Number(rep.principal || 0) + Number(rep.interest || 0) <= 0}
                  onClick={repay}
                >
                  {busy ? <Loader2 size={16} className="ss-spin" /> : "Record Repayment"}
                </button>
              </div>
            </div>
          )}
        </>
      ) : null}
    </Modal>
  );
}

/* ====================================================================
   PAGE
==================================================================== */

export default function SanghaSavings({
  user: userProp,
  onNavigate,
  onOpenAccountStatus,
  onManageAccount,
}) {
  const storedUser = useMemo(
    () => userProp ?? JSON.parse(localStorage.getItem("user") || "{}"),
    [userProp],
  );

  const [ov, setOv] = useState(null);
  const [ovLoading, setOvLoading] = useState(true);
  const [ovError, setOvError] = useState("");

  const [hist, setHist] = useState(null);
  const [histLoading, setHistLoading] = useState(true);
  const [histError, setHistError] = useState("");

  const [balanceHistory, setBalanceHistory] = useState([]);
  const [balanceHistoryLoading, setBalanceHistoryLoading] = useState(true);
  const [balanceHistoryError, setBalanceHistoryError] = useState("");
  const [snapshotError, setSnapshotError] = useState("");

  const [sanghas, setSanghas] = useState([]);
  const [sanghaId, setSanghaId] = useState(null);

  const [showRequest, setShowRequest] = useState(false);
  const [reviewId, setReviewId] = useState(null);

  // Frontend role is for layout only. The backend enforces every permission.
  const role = ov?.role ?? storedUser.role;
  const isStaff = role === "admin" || role === "superadmin";

  const load = useCallback(async (sid) => {
    setOvLoading(true);
    setHistLoading(true);
    setOvError("");
    setHistError("");
    setBalanceHistoryLoading(true);
    setBalanceHistoryError("");
    setSnapshotError("");

    const params = sid ? { sangha_id: sid } : undefined;
    const [o, h] = await Promise.allSettled([
      api.get("/sangha-savings/overview", { params }),
      api.get("/sangha-savings/history", { params }),
    ]);

    if (o.status === "fulfilled") {
      setOv(o.value.data);
      const overview = o.value.data;
      const balance = overview?.member?.availableBalance;
      if (
        overview?.role === "member"
        && typeof balance === "number"
        && Number.isFinite(balance)
        && balance >= 0
      ) {
        try {
          await api.post("/me/available-balance/snapshots");
        } catch (err) {
          console.error("Available balance snapshot failed:", err);
          setSnapshotError(errorText(err, "Unable to record today's available balance snapshot."));
        }
      }
    } else {
      console.error("Overview failed:", o.reason);
      setOvError(errorText(o.reason, "Unable to load Sangha Savings information."));
    }

    if (h.status === "fulfilled") {
      setHist(h.value.data);
    } else {
      console.error("History failed:", h.reason);
      setHistError(errorText(h.reason, "Unable to load your request history."));
    }

    const memberView = o.status === "fulfilled"
      ? o.value.data?.role === "member"
      : storedUser.role === "member";
    if (memberView) {
      try {
        const response = await api.get("/me/available-balance/history", {
          params: { days: 30 },
        });
        setBalanceHistory(response.data);
      } catch (err) {
        console.error("Available balance history failed:", err);
        setBalanceHistoryError(errorText(err, "Unable to load available balance history."));
      }
    } else {
      setBalanceHistory([]);
    }

    setOvLoading(false);
    setHistLoading(false);
    setBalanceHistoryLoading(false);
  }, [storedUser.role]);

  useEffect(() => {
    load(null);
  }, [load]);

  // Admin / superadmin can switch between the Sanghas they are allowed to see
  useEffect(() => {
    if (!isStaff) return;
    api
      .get("/sanghas")
      .then((res) => {
        const data = Array.isArray(res.data) ? res.data : (res.data?.sanghas ?? []);
        setSanghas(data);
      })
      .catch((err) => console.error("Unable to load Sanghas:", err));
  }, [isStaff]);

  useEffect(() => {
    if (ov?.sangha?.id && sanghaId === null) setSanghaId(ov.sangha.id);
  }, [ov, sanghaId]);

  const changeSangha = (e) => {
    const id = Number(e.target.value);
    setSanghaId(id);
    load(id);
  };

  const reload = () => load(sanghaId);
  const go = (id) =>
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

  const requests = hist?.requests ?? [];
  const repayments = hist?.repayments ?? [];
  const transactions = hist?.transactions ?? [];
  const reviewQueue = requests.filter((r) =>
    ["Pending", "Under Review", "Approved"].includes(r.status),
  );

  const canRequest = !!ov?.eligibility?.canRequest;

  const quickActions = isStaff
    ? [
        { label: "Review Requests", icon: ClipboardCheck, run: () => go("ss-review") },
        { label: "View Fund Health", icon: Activity, run: () => go("ss-health") },
        { label: "View Transactions", icon: Receipt, run: () => go("ss-transactions") },
        ...(onManageAccount
          ? [{ label: "Manage Savings Account", icon: Landmark, run: onManageAccount }]
          : []),
      ]
    : [
        { label: "View My Requests", icon: HandCoins, run: () => go("ss-requests") },
        { label: "View Repayments", icon: RefreshCw, run: () => go("ss-repayments") },
        {
          label: "Request Emergency Money",
          icon: Send,
          run: () => setShowRequest(true),
          disabled: !canRequest,
        },
        { label: "View Transactions", icon: Receipt, run: () => go("ss-transactions") },
      ];

  return (
    <div className="ss">
      <header className="ss-header">
        <div>
          <h1>Sangha Savings</h1>
          <p>Manage your Sangha savings, emergency support requests and repayments.</p>
        </div>

        {isStaff && sanghas.length > 0 && (
          <label className="ss-select">
            <span>Sangha</span>
            <select value={sanghaId ?? ""} onChange={changeSangha}>
              {sanghas.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                  {s.code ? ` (${s.code})` : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </header>

      {ovError && <ErrorBox text={ovError} onRetry={reload} />}

      <Snapshot isStaff={isStaff} ov={ov} loading={ovLoading} />

      {isStaff ? (
        <>
          <Section
            id="ss-review"
            title="Requests to Review"
            subtitle="Pending, under review and approved requests"
          >
            {histLoading ? (
              <Skel h={90} />
            ) : histError ? (
              <ErrorBox text={histError} onRetry={reload} />
            ) : reviewQueue.length === 0 ? (
              <Empty icon={ClipboardCheck} text="No pending requests." />
            ) : (
              <ul className="ss-queue">
                {reviewQueue.map((r) => (
                  <li key={r.id}>
                    <div>
                      <strong>{r.memberName}</strong>
                      <span>
                        {rupees(r.amount)} · {fmtDate(r.requestedAt)}
                      </span>
                    </div>
                    <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>
                    <button type="button" className="ss-btn ss-btn--soft" onClick={() => setReviewId(r.id)}>
                      {actionLabel(r.status)} <ArrowRight size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <FundHealth fund={ov?.fund} loading={ovLoading} />
          <MoneyJourney request={null} isStaff />
          <SavingsAccountCard sangha={ov?.sangha} account={ov?.account} loading={ovLoading} />
        </>
      ) : (
        <>
          <div className="ss-grid-2">
            <TrustProfile trust={ov?.member?.trust} loading={ovLoading} />
            <EmergencyCta
              eligibility={ov?.eligibility}
              loading={ovLoading}
              onRequest={() => setShowRequest(true)}
              onOpenAccountStatus={onOpenAccountStatus}
              onNavigate={onNavigate}
            />
          </div>

          <MoneyJourney request={requests[0] ?? null} isStaff={false} />
          <FinancialPosition member={ov?.member} loading={ovLoading} />
          <AvailableBalanceHistory
            items={balanceHistory}
            loading={balanceHistoryLoading}
            error={balanceHistoryError}
            snapshotError={snapshotError}
            onRetry={reload}
          />
          <SavingsAccountCard sangha={ov?.sangha} account={ov?.account} loading={ovLoading} />
        </>
      )}

      <RequestHistory
        id="ss-requests"
        title={isStaff ? "All Requests" : "Your Request History"}
        subtitle={isStaff ? "Every emergency request in this Sangha" : "Every request you have made"}
        requests={requests}
        loading={histLoading}
        error={histError}
        onRetry={reload}
        showMember={isStaff}
        isStaff={isStaff}
        onOpen={setReviewId}
      />

      <RepaymentHistory
        items={repayments}
        loading={histLoading}
        error={histError}
        onRetry={reload}
        showMember={isStaff}
      />

      <TransactionHistory
        items={transactions}
        loading={histLoading}
        error={histError}
        onRetry={reload}
        showMember={isStaff}
      />

      <QuickActions actions={quickActions} />

      {showRequest && ov?.member && ov?.fund && (
        <RequestModal
          ov={ov}
          onClose={() => setShowRequest(false)}
          onSubmitted={reload}
        />
      )}

      {reviewId !== null && (
        <ReviewModal id={reviewId} onClose={() => setReviewId(null)} onChanged={reload} />
      )}
    </div>
  );
}