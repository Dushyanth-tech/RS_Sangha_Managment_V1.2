
import { useCallback, useEffect, useState } from "react";
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
import "./MemberBankBalanceHistory.css";

const formatBalance = (balance) =>
  `₹${Number(balance).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const formatRecordedAt = (value) =>
  new Date(value).toLocaleString("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  });

const getErrorMessage = (error, fallback) =>
  error.response?.data?.detail || error.message || fallback;

export default function MemberBankBalanceHistory() {
  const [days, setDays] = useState(30);
  const [snapshots, setSnapshots] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saveMessage, setSaveMessage] = useState("");

  const requestHistory = useCallback(async () => {
    const response = await api.get("/me/bank-balance/history", {
      params: { days },
    });

    if (!Array.isArray(response.data)) {
      throw new Error("The server returned an invalid balance history.");
    }

    return response.data;
  }, [days]);

  const loadHistory = useCallback(async () => {
    setLoading(true);
    setError("");

    try {
      const history = await requestHistory();
      setSnapshots(history);
      return true;
    } catch (loadError) {
      setError(
        getErrorMessage(
          loadError,
          "Unable to load available-balance history."
        )
      );
      return false;
    } finally {
      setLoading(false);
    }
  }, [requestHistory]);

  useEffect(() => {
    let active = true;

    setLoading(true);
    setError("");

    requestHistory()
      .then((history) => {
        if (active) {
          setSnapshots(history);
          setError("");
        }
      })
      .catch((loadError) => {
        if (active) {
          setError(
            getErrorMessage(
              loadError,
              "Unable to load available-balance history."
            )
          );
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
  }, [requestHistory]);

  const recordSnapshot = async () => {
    if (saving) return;

    setSaving(true);
    setSaveError("");
    setSaveMessage("");

    try {
      const response = await api.post("/me/bank-balance/snapshots");
      const refreshed = await loadHistory();

      if (response.data?.created) {
        setSaveMessage(
          refreshed
            ? "Today's available-balance snapshot was saved."
            : "Snapshot saved, but history could not be refreshed."
        );
      } else {
        setSaveMessage(
          refreshed
            ? "Today's snapshot already exists. History has been refreshed."
            : "Today's snapshot already exists, but history could not be refreshed."
        );
      }
    } catch (saveFailure) {
      setSaveError(
        getErrorMessage(
          saveFailure,
          "Unable to save the available-balance snapshot."
        )
      );
    } finally {
      setSaving(false);
    }
  };

  const latestSnapshot = snapshots[snapshots.length - 1];

  const chartData = snapshots.map((snapshot) => ({
    ...snapshot,
    chartBalance: Number(snapshot.balance),
  }));

  return (
    <section className="mbh" aria-labelledby="mbh-title">
      <div className="mbh__header">
        <div>
          <h2 className="mbh__title" id="mbh-title">
            Available Balance History
          </h2>
          <p className="mbh__subtitle">
            Track the available balance calculated by RS-Sangha.
            This is not a live personal bank-account balance.
          </p>
        </div>

        <label className="mbh__range">
          <span>Date range</span>
          <select
            value={days}
            onChange={(event) => setDays(Number(event.target.value))}
          >
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={365}>Last 365 days</option>
          </select>
        </label>
      </div>

      <div className="mbh__latest" aria-live="polite">
        <span className="mbh__latest-label">
          Latest recorded balance
        </span>

        <strong>
          {loading
            ? "Loading..."
            : error
              ? "Unavailable"
              : latestSnapshot
                ? formatBalance(latestSnapshot.balance)
                : "No snapshot"}
        </strong>

        {latestSnapshot && (
          <span className="mbh__latest-date">
            Recorded {formatRecordedAt(latestSnapshot.recorded_at)}
          </span>
        )}
      </div>


      {saveError && (
        <p className="mbh__message mbh__message--error" role="alert">
          {saveError}
        </p>
      )}

      {saveMessage && (
        <p className="mbh__message mbh__message--success" role="status">
          {saveMessage}
        </p>
      )}

      {loading ? (
        <p className="mbh__state" role="status">
          Loading balance history...
        </p>
      ) : error ? (
        <div className="mbh__state mbh__state--error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={loadHistory}>
            Retry
          </button>
        </div>
      ) : snapshots.length === 0 ? (
        <p className="mbh__state">
          No recorded balance snapshots in the selected period.
          Save today's snapshot to start tracking your history.
        </p>
      ) : (
        <>
          {chartData.length > 1 && (
            <div className="mbh__chart">
              <ResponsiveContainer width="100%" height={240}>
                <LineChart
                  data={chartData}
                  margin={{
                    top: 12,
                    right: 16,
                    bottom: 8,
                    left: 8,
                  }}
                >
                  <CartesianGrid strokeDasharray="3 3" />

                  <XAxis
                    dataKey="recorded_at"
                    tickFormatter={(value) =>
                      new Date(value).toLocaleDateString("en-IN")
                    }
                  />

                  <YAxis
                    tickFormatter={(value) =>
                      `₹${Number(value).toLocaleString("en-IN")}`
                    }
                    width={82}
                  />

                  <Tooltip
                    labelFormatter={(value) => formatRecordedAt(value)}
                    formatter={(value) => [
                      formatBalance(value),
                      "Available balance",
                    ]}
                  />

                  <Line
                    type="linear"
                    dataKey="chartBalance"
                    name="Recorded balance"
                    stroke="#373276"
                    strokeWidth={2}
                    dot={{ r: 4 }}
                    activeDot={{ r: 6 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          <div className="mbh__table-wrap">
            <table className="mbh__table">
              <caption>
                Recorded available-balance snapshots
              </caption>

              <thead>
                <tr>
                  <th scope="col">Recorded at</th>
                  <th scope="col">Balance</th>
                  <th scope="col">Recorded from</th>
                </tr>
              </thead>

              <tbody>
                {snapshots.map((snapshot) => (
                  <tr key={snapshot.id}>
                    <td>{formatRecordedAt(snapshot.recorded_at)}</td>
                    <td>{formatBalance(snapshot.balance)}</td>
                    <td>{snapshot.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
