
import { useState } from "react";
import { BriefcaseBusiness, IndianRupee, House } from "lucide-react";
import api from "../../../../api/axiosInstance";
import "./EmploymentProfileModal.css";

export default function EmploymentProfileModal({ onCompleted }) {
  const [employmentType, setEmploymentType] = useState("");
  const [professional, setProfessional] = useState("");
  const [salary, setSalary] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (event) => {
    event.preventDefault();
    setError("");

    if (!employmentType) {
      setError("Please select your employment status.");
      return;
    }

    if (
      employmentType === "other" &&
      (!professional.trim() || salary === "" || Number(salary) < 0)
    ) {
      setError("Enter your profession and a valid monthly salary.");
      return;
    }

    try {
      setSaving(true);

      await api.patch("/me/employment-profile", {
        employment_type: employmentType,
        professional:
          employmentType === "other" ? professional.trim() : null,
        salary:
          employmentType === "other" ? salary : null,
      });

      onCompleted();
    } catch (requestError) {
      setError(
        requestError.response?.data?.detail ||
          "Unable to save your employment details. Please try again."
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="employment-overlay">
      <section
        className="employment-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="employment-title"
      >
        <div className="employment-modal__icon">
          <BriefcaseBusiness size={25} />
        </div>

        <p className="employment-modal__eyebrow">
          MEMBER PROFILE
        </p>

        <h2 id="employment-title">
          Tell us about your work
        </h2>

        <p className="employment-modal__description">
          Please complete these details to continue to your dashboard.
        </p>

        <form onSubmit={handleSubmit}>
          <fieldset className="employment-options">
            <legend>What best describes you?</legend>

            <label
              className={`employment-option ${
                employmentType === "house_wife"
                  ? "employment-option--selected"
                  : ""
              }`}
            >
              <input
                type="radio"
                name="employmentType"
                value="house_wife"
                checked={employmentType === "house_wife"}
                onChange={() => {
                  setEmploymentType("house_wife");
                  setProfessional("");
                  setSalary("");
                  setError("");
                }}
              />

              <span className="employment-option__icon">
                <House size={21} />
              </span>

              <span className="employment-option__text">
                <strong>House wife</strong>
                <small>Not currently employed outside the home</small>
              </span>
            </label>

            <label
              className={`employment-option ${
                employmentType === "other"
                  ? "employment-option--selected"
                  : ""
              }`}
            >
              <input
                type="radio"
                name="employmentType"
                value="other"
                checked={employmentType === "other"}
                onChange={() => {
                  setEmploymentType("other");
                  setError("");
                }}
              />

              <span className="employment-option__icon">
                <BriefcaseBusiness size={21} />
              </span>

              <span className="employment-option__text">
                <strong>Other</strong>
                <small>Working professional, self-employed, etc.</small>
              </span>
            </label>
          </fieldset>

          {employmentType === "other" && (
            <div className="employment-fields">
              <label htmlFor="employment-profession">
                Profession
              </label>

              <input
                id="employment-profession"
                type="text"
                placeholder="e.g. Teacher, Tailor, Software Engineer"
                value={professional}
                onChange={(event) =>
                  setProfessional(event.target.value)
                }
                maxLength={100}
                required
              />

              <label htmlFor="employment-salary">
                Monthly salary (₹)
              </label>

              <div className="employment-salary-input">
                <IndianRupee size={18} />
                <input
                  id="employment-salary"
                  type="number"
                  placeholder="Enter monthly salary"
                  value={salary}
                  onChange={(event) => setSalary(event.target.value)}
                  min="0"
                  max="9999999999.99"
                  step="0.01"
                  required
                />
              </div>
            </div>
          )}

          {error && (
            <p className="employment-error" role="alert">
              {error}
            </p>
          )}

          <button
            type="submit"
            className="employment-submit"
            disabled={
              saving ||
              !employmentType ||
              (employmentType === "other" &&
                (!professional.trim() || salary === ""))
            }
          >
            {saving ? "Saving details..." : "Submit and continue"}
          </button>

          <p className="employment-modal__footer">
            Your details will be saved securely to your member profile.
          </p>
        </form>
      </section>
    </div>
  );
}
