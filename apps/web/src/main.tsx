import { useEffect, useState, type FormEvent } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

type AppName = "manufacturing" | "storage" | "logistics" | "shipping" | "twin";
const appName = (import.meta as unknown as { env: Record<string, string> }).env
  .VITE_SIMULATOR as AppName;
const names: Record<AppName, string> = {
  manufacturing: "Manufacturing",
  storage: "Storage",
  logistics: "Logistics",
  shipping: "Shipping",
  twin: "Digital twin",
};
const descriptions: Record<AppName, string> = {
  manufacturing: "Production simulation foundation",
  storage: "Warehouse simulation foundation",
  logistics: "Transport simulation foundation",
  shipping: "Dispatch simulation foundation",
  twin: "Independent source monitoring",
};
type Run = {
  id: string;
  epoch: string;
  mode: string;
  state: string;
  granted: number;
  requested: number;
  committed: number;
  speed: number;
  error: string | null;
  blocked_reason: string | null;
  scenario: {
    time_zone: string;
    seed: number;
    business_open: string;
    business_close: string;
  };
};
type Job = {
  id: string;
  due_at: number;
  status: string;
  attempts: number;
  payload: { quantity: number };
  idempotency_key: string;
  error: string | null;
  boundary_input: { kind: string; boundary: string } | null;
};
type AuditEvent = {
  id: string;
  actor: string;
  role: string;
  action: string;
  outcome: string;
  status_code: number;
  recorded_at: string;
  request_id: string;
};
type Status = {
  identity: { username: string; role: string; scopes: string[] };
  simulation_time: string;
  application: string;
  run: Run;
  jobs: Job[];
  effects: number;
  quantum: number;
  providers: Record<string, string>;
  heartbeats: { role: string; healthy: boolean }[];
  pending_boundary_outputs: number;
};
type Source = {
  name: string;
  connected: boolean;
  observed_at: string;
  error: string | null;
  status: Status | null;
};

function App() {
  const [auth, setAuth] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [error, setError] = useState("");
  const [stale, setStale] = useState(false);
  const [busy, setBusy] = useState(false);
  const [quantity, setQuantity] = useState(1);
  const [filter, setFilter] = useState("");
  const [section, setSection] = useState<"overview" | "operator" | "audit">(
    "overview",
  );
  const [resetting, setResetting] = useState(false);
  const isTwin = appName === "twin";
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const canControl = status?.identity.scopes.includes("runs:control") ?? false;
  const canSubmit = status?.identity.scopes.includes("jobs:write") ?? false;
  const canAudit = status?.identity.scopes.includes("audit:read") ?? false;

  async function request<T>(
    path: string,
    credential = auth,
    body?: object,
    key?: string,
  ): Promise<T> {
    const response = await fetch("/api/" + path, {
      method: body ? "POST" : "GET",
      headers: {
        Authorization: "Basic " + credential,
        ...(body ? { "Content-Type": "application/json" } : {}),
        ...(key ? { "Idempotency-Key": key } : {}),
      },
      ...(body ? { body: JSON.stringify(body) } : {}),
    });
    const data = await response.json();
    if (!response.ok)
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : "Check the command values and try again.",
      );
    return data;
  }

  useEffect(() => {
    if (!auth) return;
    let alive = true;
    async function refresh() {
      try {
        const data = await request<Status>("status");
        const sourceData = isTwin ? await request<Source[]>("sources") : [];
        const auditData =
          section === "audit" && data.identity.scopes.includes("audit:read")
            ? await request<AuditEvent[]>("audit")
            : [];
        if (alive) {
          setAudit(auditData);
          setStatus(data);
          setSources(sourceData);
          setStale(false);
        }
      } catch {
        if (alive) setStale(true);
      }
    }
    void refresh();
    const timer = setInterval(() => void refresh(), 1500);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [auth, section]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const values = new FormData(event.currentTarget);
    const credential = btoa(
      unescape(
        encodeURIComponent(
          values.get("username") + ":" + values.get("password"),
        ),
      ),
    );
    try {
      const data = await request<Status>("status", credential);
      setStatus(data);
      setAuth(credential);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function control(action: string, extra: object = {}) {
    setBusy(true);
    setError("");
    try {
      await request("control/" + action, auth, extra);
      setStatus(await request<Status>("status"));
      setResetting(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function schedule(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const current = await request<Status>("status");
      await request(
        "jobs",
        auth,
        {
          due_at:
            Math.max(current.run.granted, current.run.requested) +
            Math.max(5, current.quantum),
          quantity,
        },
        crypto.randomUUID(),
      );
      setStatus(await request<Status>("status"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const run = status?.run;
  return (
    <div className="shell">
      <aside>
        <a className="wordmark" href="/">
          {names[appName]}
          <small>SIMULATOR</small>
        </a>
        <div className="sidebar-bottom">
          {descriptions[appName]}
          <span>Application bootstrap · V0.1</span>
        </div>
        {auth && (
          <nav aria-label="Application">
            <button
              aria-current={section === "overview" ? "page" : undefined}
              onClick={() => setSection("overview")}
            >
              {isTwin ? "Sources" : "Sample activity"}
            </button>
            {canControl && (
              <button
                aria-current={section === "operator" ? "page" : undefined}
                onClick={() => setSection("operator")}
              >
                Operator
              </button>
            )}
            {canAudit && (
              <button
                aria-current={section === "audit" ? "page" : undefined}
                onClick={() => setSection("audit")}
              >
                Audit history
              </button>
            )}
          </nav>
        )}
      </aside>
      <main>
        <header>
          <span>
            {isTwin ? "Source monitor" : "Independent business simulator"}
          </span>
          {auth && (
            <button
              className="quiet"
              onClick={() => {
                setAuth("");
                setStatus(null);
                setError("");
                setSection("overview");
                setAudit([]);
              }}
            >
              Sign out
            </button>
          )}
        </header>
        {!auth ? (
          <section className="login">
            <p className="eyebrow">{names[appName]}</p>
            <h1>Sign in</h1>
            <p>Use this application’s configured account.</p>
            <form onSubmit={login}>
              <label>
                Username
                <input
                  name="username"
                  autoComplete="username"
                  required
                  defaultValue={appName + "-operator"}
                />
              </label>
              <label>
                Password
                <input
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  required
                />
              </label>
              <button className="primary" disabled={busy}>
                Sign in
              </button>
            </form>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
          </section>
        ) : (
          <>
            <div className="title-row">
              <div>
                <p className="eyebrow">{descriptions[appName]}</p>
                <h1>
                  {section === "audit"
                    ? "Command audit"
                    : section === "operator"
                      ? "Run controls"
                      : isTwin
                        ? "Connected sources"
                        : "Sample activity"}
                </h1>
              </div>
              <span className={"badge " + (stale ? "error" : "")}>
                {stale ? "Connection lost" : isTwin ? "Monitoring" : run?.state}
              </span>
            </div>
            {stale && (
              <p role="alert" className="error">
                The application is unreachable. Displayed data may be stale.
              </p>
            )}
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            {run?.error && (
              <p role="alert" className="error">
                {run.error}
              </p>
            )}
            {section === "overview" && !isTwin && (
              <>
                <p className="intro">
                  Schedule a sample operation to verify durable processing.
                  Department workflows will be added in the application V1.
                </p>
                <div className="metrics">
                  <Metric
                    label="Committed time"
                    value={run?.committed ?? 0}
                    unit="s"
                  />
                  <Metric
                    label="Granted time"
                    value={run?.granted ?? 0}
                    unit="s"
                  />
                  <Metric
                    label="Sample effect total"
                    value={status?.effects ?? 0}
                    unit="items"
                  />
                </div>
                <div className="split">
                  <section className="panel">
                    <div className="panel-heading">
                      <h2>Work ledger</h2>
                      <input
                        aria-label="Filter sample jobs"
                        placeholder="Filter jobs"
                        value={filter}
                        onChange={(e) => setFilter(e.target.value)}
                      />
                    </div>
                    <div className="table-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Operation</th>
                            <th>Due</th>
                            <th>Quantity</th>
                            <th>Status</th>
                          </tr>
                        </thead>
                        <tbody>
                          {status?.jobs
                            .filter((job) =>
                              (job.status + " " + job.idempotency_key).includes(
                                filter,
                              ),
                            )
                            .map((job) => (
                              <tr key={job.id}>
                                <td title={job.id}>
                                  {job.boundary_input
                                    ? job.boundary_input.kind + " input"
                                    : job.idempotency_key.startsWith(
                                          "synthetic",
                                        )
                                      ? "Autonomous sample"
                                      : job.idempotency_key.startsWith(
                                            "boundary:",
                                          )
                                        ? "Peer sample"
                                        : "Employee sample"}
                                  <small>
                                    {job.id.slice(0, 8)}
                                    {job.error && " · " + job.error}
                                  </small>
                                </td>
                                <td>{job.due_at}s</td>
                                <td>{job.payload.quantity}</td>
                                <td>
                                  <span className="badge">{job.status}</span>
                                </td>
                              </tr>
                            ))}
                        </tbody>
                      </table>
                      {!status?.jobs.length && (
                        <p className="empty">
                          No operations in this run. Schedule a sample or wait
                          for autonomous activity.
                        </p>
                      )}
                    </div>
                  </section>
                  <section className="panel">
                    <h2>Schedule sample</h2>
                    <p>
                      The sample records an item count exactly once. It does not
                      move real inventory.
                    </p>
                    <form onSubmit={schedule}>
                      <label>
                        Quantity
                        <input
                          type="number"
                          min="1"
                          max="10000"
                          required
                          value={quantity}
                          onChange={(e) => setQuantity(Number(e.target.value))}
                        />
                      </label>
                      <p className="muted">
                        Due at least {Math.max(5, status?.quantum ?? 1)}{" "}
                        simulation seconds after the current requested time.
                        Held runs retain pending work.
                      </p>
                      <button
                        className="primary"
                        disabled={
                          busy ||
                          stale ||
                          !["running", "held"].includes(run?.state ?? "")
                        }
                      >
                        Schedule operation
                      </button>
                    </form>
                  </section>
                </div>
              </>
            )}
            {section === "overview" && isTwin && (
              <>
                <p className="intro">
                  Each source owns its clock and state. This website observes
                  configured simulator APIs.
                </p>
                {!sources.length ? (
                  <section className="panel empty-state">
                    <h2>No sources configured</h2>
                    <p>
                      The digital twin is running independently. Add simulator
                      API addresses and credentials to its source configuration
                      to begin monitoring.
                    </p>
                  </section>
                ) : (
                  <div className="source-grid">
                    {sources.map((source) => (
                      <section className="panel" key={source.name}>
                        <div className="panel-heading">
                          <h2>
                            {names[source.name as AppName] ?? source.name}
                          </h2>
                          <span className="badge">
                            {source.connected ? "Connected" : "Disconnected"}
                          </span>
                        </div>
                        <p>{source.error}</p>
                        <Metric
                          label="Committed time"
                          value={source.status?.run.committed ?? 0}
                          unit="s"
                        />
                        <p>
                          Granted {source.status?.run.granted ?? "—"}s ·{" "}
                          {source.status?.run.state ?? "Unknown"}
                        </p>
                        <p className="muted">
                          Last checked{" "}
                          {source.observed_at
                            ? new Date(source.observed_at).toLocaleTimeString()
                            : "Never"}
                        </p>
                      </section>
                    ))}
                  </div>
                )}
                <p className="muted">
                  Per-source watermarks are independent; these snapshots are not
                  a federation-wide atomic view.
                </p>
              </>
            )}
            {section === "operator" && canControl && (
              <>
                <section className="panel">
                  <h2>{isTwin ? "Projection health" : "Clock and run"}</h2>
                  {!isTwin && (
                    <>
                      <div className="metrics">
                        <Metric
                          label="Requested"
                          value={run?.requested ?? 0}
                          unit="s"
                        />
                        <Metric
                          label="Granted"
                          value={run?.granted ?? 0}
                          unit="s"
                        />
                        <Metric
                          label="Committed"
                          value={run?.committed ?? 0}
                          unit="s"
                        />
                      </div>
                      <p>
                        Clock mode: <strong>{run?.mode}</strong>.{" "}
                        {run?.mode === "helics"
                          ? "Local hold can delay peers; it does not acknowledge a federation-wide pause."
                          : "Local hold freezes this simulator’s business time."}
                      </p>
                      <p>
                        Business time: {status?.simulation_time} ·{" "}
                        {run?.scenario.time_zone}
                      </p>
                      <p>
                        Seed {run?.scenario.seed}; business hours{" "}
                        {run?.scenario.business_open}–
                        {run?.scenario.business_close}
                      </p>
                      <div className="controls">
                        <button
                          disabled={
                            busy ||
                            stale ||
                            !canSubmit ||
                            !["running", "held"].includes(run?.state ?? "")
                          }
                          onClick={() =>
                            void control(
                              run?.state === "held" ? "resume" : "hold",
                            )
                          }
                        >
                          {run?.state === "held" ? "Resume" : "Hold"}
                        </button>
                        {run?.mode === "standalone" && (
                          <label>
                            Speed
                            <select
                              aria-label="Simulation speed"
                              value={run.speed}
                              disabled={busy || stale}
                              onChange={(e) =>
                                void control("speed", {
                                  speed: Number(e.target.value),
                                })
                              }
                            >
                              {[1, 5, 20, 60].map((n) => (
                                <option key={n} value={n}>
                                  {n}×
                                </option>
                              ))}
                            </select>
                          </label>
                        )}
                        <button
                          disabled={busy || stale || run?.state === "finalized"}
                          onClick={() => void control("finalize")}
                        >
                          Finalize run
                        </button>
                        {run?.mode === "standalone" && (
                          <button
                            className="danger"
                            disabled={busy || stale}
                            onClick={() => setResetting(true)}
                          >
                            Reset run
                          </button>
                        )}
                      </div>
                      {resetting && (
                        <div
                          className="confirm"
                          role="alertdialog"
                          aria-label="Confirm reset"
                        >
                          <p>
                            Reset starts a new run and epoch. Existing work
                            remains archived and cannot affect the new run.
                          </p>
                          <button
                            disabled={busy}
                            onClick={() =>
                              void control("reset", { confirm_run_id: run?.id })
                            }
                          >
                            Confirm reset
                          </button>
                          <button onClick={() => setResetting(false)}>
                            Cancel
                          </button>
                        </div>
                      )}
                      <dl>
                        <dt>Run ID</dt>
                        <dd>{run?.id}</dd>
                        <dt>Epoch</dt>
                        <dd>{run?.epoch}</dd>
                      </dl>
                    </>
                  )}
                  <h3>Processes</h3>
                  <ul className="processes">
                    {status?.heartbeats.map((item) => (
                      <li key={item.role}>
                        {item.role}
                        <span className="badge">
                          {item.healthy ? "Healthy" : "Unavailable"}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {!status?.heartbeats.length && (
                    <p>Waiting for process heartbeats.</p>
                  )}
                </section>
                {!isTwin && (
                  <section className="panel">
                    <h2>Boundary providers</h2>
                    <p>
                      Provider choices are explicit. Peer failure never
                      activates synthetic inputs.
                    </p>
                    <ul className="processes">
                      {Object.entries(status?.providers ?? {}).map(
                        ([boundary, provider]) => (
                          <li key={boundary}>
                            {boundary}
                            <span>{provider}</span>
                          </li>
                        ),
                      )}
                    </ul>
                  </section>
                )}
              </>
            )}
          </>
        )}
        {auth && section === "audit" && canAudit && (
          <section className="panel">
            <h2>Accepted and rejected commands</h2>
            <p>
              Most recent 100 attempts across retained runs. Passwords and
              request bodies are excluded.
            </p>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th>Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.map((event) => (
                    <tr key={event.id}>
                      <td>{new Date(event.recorded_at).toLocaleString()}</td>
                      <td>
                        {event.actor}
                        <small>{event.role}</small>
                      </td>
                      <td>
                        {event.action}
                        <small>{event.request_id}</small>
                      </td>
                      <td>
                        {event.outcome} ({event.status_code})
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
        <footer>
          {names[appName]} · Independent website · Simulation data only
        </footer>
      </main>
    </div>
  );
}
function Metric({
  label,
  value,
  unit,
}: {
  label: string;
  value: number;
  unit: string;
}) {
  return (
    <div className="metric">
      <p>{label}</p>
      <strong>
        {value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
        <small>{unit}</small>
      </strong>
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
