import React from "react";
import { X } from "lucide-react";
import "../pages/MySangha.css";
import "./ScoreBreakdownModal.css";

const STATUS_TEXT = {
  sufficient: "Reliable score",
  provisional: "Provisional score - based on limited history, so it may change as you add more activity.",
  insufficient_data: "Not enough activity recorded yet to calculate a score.",
};

const formatDate = (value) => {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
};

const rupees = (value) => `₹${Number(value || 0).toLocaleString("en-IN")}`;

function factorState(factor) {
  if (factor.status !== "calculated") return { text: "Needs more data", tone: "need" };
  if (!factor.reliable) return { text: "Early estimate", tone: "early" };
  return { text: "Calculated", tone: "ok" };
}

export default function ScoreBreakdownModal({ data, onClose }) {
  if (!data) return null;

  return (
    <div className="md-modal-overlay" onClick={onClose}>
      <div className="md-modal" onClick={(e) => e.stopPropagation()}>
        <div className="md-modal__header">
          <div>
            <h2>RS-Sangha Score</h2>
            <p>Internal score out of {data.max_score}. Not an official CIBIL score.</p>
          </div>
          <button type="button" className="md-modal__close" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </div>

        <div className="md-modal__body">
          <div className="sb-summary">
            {data.score != null ? (
              <strong>
                {data.score} / {data.max_score}
                {data.category ? ` - ${data.category}` : ""}
              </strong>
            ) : (
              <strong>No score yet</strong>
            )}
            <span>{STATUS_TEXT[data.status] ?? ""}</span>
            {data.first_activity_date && (
              <small>Tracking since {formatDate(data.first_activity_date)}</small>
            )}
          </div>

          <ul className="sb-factors">
            {data.factors?.map((factor) => {
              const state = factorState(factor);
              return (
                <li key={factor.key} className="sb-factor">
                  <div className="sb-factor__top">
                    <span className="sb-factor__name">
                      {factor.label} <em>{factor.weight}%</em>
                    </span>
                    <span className={`sb-chip sb-chip--${state.tone}`}>{state.text}</span>
                  </div>
                  {factor.score != null && (
                    <div className="sb-bar" aria-hidden="true">
                      <span style={{ width: `${Math.max(0, Math.min(100, factor.score))}%` }} />
                    </div>
                  )}
                  <p className="sb-factor__detail">{factor.detail}</p>
                </li>
              );
            })}
          </ul>

          {data.loans?.length > 0 && (
            <div className="sb-loans">
              <h3>Your loans</h3>
              {data.loans.map((loan) => (
                <div key={loan.request_id} className="sb-loan">
                  <span>
                    {rupees(loan.amount)} - {loan.status}
                    {loan.disbursed_at ? `, received ${formatDate(loan.disbursed_at)}` : ""}
                  </span>
                  <small>
                    Principal outstanding {rupees(loan.outstanding_principal)}
                    {loan.next_interest_due ? `. Next interest due ${formatDate(loan.next_interest_due)}` : ""}
                    {loan.interest_cycles_overdue > 0
                      ? `. ${loan.interest_cycles_overdue} interest due date(s) passed unpaid`
                      : ""}
                  </small>
                </div>
              ))}
            </div>
          )}

          <p className="sb-note">
            Factors that do not have enough information yet are left out of the score. They are
            never counted as zero and never given full points.
          </p>
        </div>
      </div>
    </div>
  );
}