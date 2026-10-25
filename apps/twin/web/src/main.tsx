import HandlingInspector from './HandlingInspector';
import type {RecordedUnit} from './facility';
import {
  useEffect,
  useState,
  type FormEvent,
} from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import Facility3D from "./Facility3D";

type Row = Record<string, unknown>;
type Run = {
  id: string;
  epoch: string;
  state: string;
  granted: number;
  requested: number;
  committed: number;
  speed?: number;
  blocked_reason?: string | null;
  scenario?: { start_at?: string; time_zone?: string };
};
type Heartbeat = { role: string; healthy: boolean; seen_at?: string };
type Source = {
  name: string;
  connected: boolean;
  stale: boolean;
  observed_at: string | null;
  last_success_at: string | null;
  error: string | null;
  status: { run: Run } | null;
  snapshot: Row | null;
  cursor: string | null;
  website_url: string | null;
  health?: {
    heartbeats?: Heartbeat[];
    pending_jobs?: number;
    dead_letters?: number;
    ready?: boolean;
    broker?: { healthy: boolean } | boolean | null;
  };
};
type Event = {
  id: string;
  source: string;
  run_id: string;
  epoch: string;
  correlation_id?: string;
  simulation_time?: number;
  payload: Row;
};
type Twin = {
  fleet?:import('./fleetState').FleetObservation|null;
  handling?: {version: number; units: RecordedUnit[]; unsupported_sources: string[]};
  revision: number;
  mode: "live";
  sources: Source[];
  events: Event[];
  heartbeats?: Heartbeat[];
  aligned: { committed: number; run_id: string; epoch: string } | null;
  controls: {
    name: string;
    label: string;
    scope: "local" | "federation";
    source: string | null;
    actions: string[];
  }[];
};
type PendingControl = {
  target: Twin["controls"][number];
  action: string;
  body: Row;
  key: string;
};
type Identity = {
  identity: { username: string; scopes: string[] };
  heartbeats?: { role: string; healthy: boolean }[];
};
type Entity = {
  key: string;
  label: string;
  kind: string;
  source: Source;
  row: Row;
  related: Row[];
  x: number;
  y: number;
};
const names: Record<string, string> = {
  manufacturing: "Manufacturing",
  storage: "Storage",
  logistics: "Logistics",
  shipping: "Shipping",
};
const rows = (value: unknown): Row[] =>
  Array.isArray(value)
    ? value.filter(
        (r): r is Row => !!r && typeof r === "object" && !Array.isArray(r),
      )
    : [];
const object = (value: unknown): Row =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Row)
    : {};
const str = (value: unknown) =>
  value === null || value === undefined
    ? "Unavailable"
    : typeof value === "object"
      ? JSON.stringify(value)
      : String(value);
const time = (value: unknown) =>
  typeof value === "number" && Number.isFinite(value)
    ? `${Number(value.toFixed(2))} s`
    : "Unavailable";
const health = (source: Source) =>
  !source.connected ? "Disconnected" : source.stale ? "Stale" : "Connected";
const date = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "Never";
function calendar(run: Run | undefined) {
  if (
    !run?.scenario?.start_at ||
    !run.scenario.time_zone ||
    !Number.isFinite(run.granted)
  )
    return "Calendar unavailable";
  try {
    const value = new Date(
      new Date(run.scenario.start_at).getTime() + run.granted * 1000,
    );
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "medium",
      timeZone: run.scenario.time_zone,
      hour12: false,
    }).format(value);
  } catch {
    return "Calendar unavailable";
  }
}
function safeWebsite(value: string | null) {
  try {
    const url = new URL(value ?? "");
    return ["http:", "https:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}
function entities(sources: Source[]): Entity[] {
  const result: Entity[] = [];
  for (const source of sources) {
    const data = source.snapshot;
    if (!data) continue;
    const add = (
      kind: string,
      row: Row,
      index: number,
      x: number,
      y: number,
      related: Row[] = [],
    ) =>
      result.push({
        key: `${source.name}:${kind}:${str(row.code ?? row.id ?? index)}`,
        label: str(row.code ?? row.id ?? row.location ?? kind),
        kind,
        source,
        row,
        related,
        x: 120 + 0.9 * x + 0.38 * y,
        y: 185 - 0.25 * x + 0.72 * y,
      });
    if (source.name === "manufacturing")
      rows(object(data.config).lines).forEach((r, i) =>
        add(
          "production cell",
          r,
          i,
          80 + (i % 3) * 85,
          85 + Math.floor(i / 3) * 60,
          rows(data.orders).filter((o) => o.line === r.code),
        ),
      );
    if (source.name === "storage")
      rows(data.locations).forEach((r, i) =>
        add(
          r.code === "DISPATCH" ? "loading bay" : "storage rack",
          r,
          i,
          370 + (i % 3) * 85,
          80 + Math.floor(i / 3) * 60,
          [
            ...rows(data.inventory).filter((o) => o.location === r.code),
            ...rows(data.transfers).filter(
              (o) => o.origin === r.code || o.destination === r.code,
            ),
          ],
        ),
      );
    if (source.name === "shipping")
      rows(data.orders).forEach((r, i) =>
        add(
          "order",
          r,
          i,
          380 + (i % 3) * 78,
          365 + Math.floor(i / 3) * 40,
          rows(data.shipments).filter((o) => o.order_id === r.id),
        ),
      );
    if (source.name === "logistics")
      rows(data.vehicles).forEach((r, i) =>
        add(
          "vehicle",
          r,
          i,
          80 + (i % 3) * 85,
          340 + Math.floor(i / 3) * 55,
          rows(data.transfers).filter((o) => o.vehicle === r.code),
        ),
      );
  }
  return result;
}
function App() {
  const [auth, setAuth] = useState("");
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [twin, setTwin] = useState<Twin | null>(null);
  const [error, setError] = useState("");
  const [lost, setLost] = useState(false);
  const [busy, setBusy] = useState(false);
  const [controlMessage, setControlMessage] = useState("");
  const [pendingControl, setPendingControl] = useState<PendingControl | null>(
    null,
  );
  const [section, setSection] = useState("facility");
  const [selected, setSelected] = useState("");
  const [record, setRecord] = useState<Row | null>(null);
  const [search, setSearch] = useState("");
  async function request<T>(path: string, credential = auth): Promise<T> {
    const response = await fetch("/api/" + path, {
      headers: { Authorization: "Basic " + credential },
      cache: "no-store",
    });
    if (!response.ok)
      throw new Error(
        response.status === 401
          ? "Check your username and password."
          : "Twin data is unavailable.",
      );
    return response.json() as Promise<T>;
  }
  useEffect(() => {
    if (!auth) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const data = await request<Twin>("twin");
        if (alive) {
          setTwin((previous) =>
            !previous || data.revision >= previous.revision ? data : previous,
          );
          setLost(false);
        }
      } catch {
        if (alive) setLost(true);
      } finally {
        if (alive) timer = setTimeout(() => void refresh(), 2000);
      }
    }
    void refresh();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [auth]);
  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    const credential = btoa(
      unescape(
        encodeURIComponent(form.get("username") + ":" + form.get("password")),
      ),
    );
    try {
      setIdentity(await request<Identity>("status", credential));
      setAuth(credential);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function control(target: Twin["controls"][number], action: string) {
    if (!identity?.identity.scopes.includes("runs:control")) return;
    if (
      pendingControl &&
      (pendingControl.target.name !== target.name ||
        pendingControl.action !== action)
    )
      return;
    const source = twin?.sources.find((s) => s.name === target.source);
    const command = pendingControl ?? {
      target,
      action,
      key: crypto.randomUUID(),
      body:
        target.scope === "local"
          ? { run_id: source?.status?.run.id, epoch: source?.status?.run.epoch }
          : {},
    };
    setPendingControl(command);
    setBusy(true);
    setControlMessage("");
    try {
      const response = await fetch(
        `/api/twin/controls/${encodeURIComponent(command.target.name)}/${encodeURIComponent(command.action)}`,
        {
          method: "POST",
          headers: {
            Authorization: "Basic " + auth,
            "Content-Type": "application/json",
            "Idempotency-Key": command.key,
          },
          body: JSON.stringify(command.body),
        },
      );
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) {
          setPendingControl(null);
          setControlMessage(
            "Control request rejected. Refresh source state before issuing another request.",
          );
          return;
        }
        throw new Error(
          "Control outcome is unknown. Retry the pending request with the same key.",
        );
      }
      const result = (await response.json()) as {
        acknowledged: boolean;
        message: string;
      };
      if (result.acknowledged) setPendingControl(null);
      setControlMessage(
        (result.acknowledged
          ? "Acknowledged: "
          : "Awaiting acknowledgement: ") + result.message,
      );
    } catch {
      setControlMessage(
        "Control outcome is unknown. Retry the pending request with the same key.",
      );
    } finally {
      setBusy(false);
    }
  }
  const unitEntities: Entity[] = (twin?.handling?.units ?? []).flatMap(unit => {
    const source = twin?.sources.find(source => source.name === unit.owner) ??
      twin?.sources.find(source => source.name === unit.observations[0]?.source);
    if (!source) return [];
    return [{key:`unit:${unit.run_id}:${unit.epoch}:${unit.id}`,label:unit.barcode,kind:'handling unit',
      source,row:unit as unknown as Row,related:[],x:0,y:0}];
  });
  const all = [...unitEntities, ...entities(twin?.sources ?? [])];
  const entity = all.find((e) => e.key === selected);
  const selectedUnit=twin?.handling?.units.find(unit=>`unit:${unit.run_id}:${unit.epoch}:${unit.id}`===selected);
  const currentRecord =
    record && entity
      ? ([entity.row, ...entity.related].find(
          (r) =>
            r.id === record.id &&
            r.code === record.code &&
            r.sku === record.sku &&
            r.location === record.location,
        ) ?? null)
      : null;
  const detail = currentRecord ?? entity?.row;
  const choose = (e: Pick<Entity, "key">) => {
    setSelected(e.key);
    setRecord(null);
  };
  const correlation = detail?.correlation_id;
  const correlatedRecords = (twin?.sources ?? []).flatMap((source) =>
    ["orders", "transfers", "shipments"].flatMap((kind) =>
      rows(source.snapshot?.[kind])
        .filter((row) => correlation && row.correlation_id === correlation)
        .map((row) => ({ source, kind, row })),
    ),
  );
  const relatedEvents = (twin?.events ?? []).filter((e) => {
    const source = twin?.sources.find((s) => s.name === e.source);
    if (
      !source?.status ||
      e.run_id !== source.status.run.id ||
      e.epoch !== source.status.run.epoch
    )
      return false;
    return (
      !entity ||
      (correlation
        ? e.correlation_id === correlation
        : e.source === entity.source.name &&
          (Object.values(e.payload).includes(detail?.id) ||
            Object.values(e.payload).includes(detail?.code) ||
            Object.values(e.payload).includes(detail?.location)))
    );
  });
  const ledger = (twin?.sources ?? [])
    .flatMap((source) =>
      [
        "orders",
        "transfers",
        "movements",
        "receipts",
        "reservations",
        "shipments",
        "materials",
        "inventory",
      ].flatMap((kind) =>
        rows(source.snapshot?.[kind]).map((row) => ({ source, kind, row })),
      ),
    )
    .filter((item) =>
      JSON.stringify(item.row).toLowerCase().includes(search.toLowerCase()),
    );
  return (
    <div className="shell">
      <aside className="sidebar">
        <a href="/" className="wordmark">
          Digital twin<span>Facility observer</span>
        </a>
        {auth && (
          <nav aria-label="Application">
            {["facility", "activity", "infrastructure"].map((item) => (
              <button
                key={item}
                aria-current={section === item ? "page" : undefined}
                onClick={() => setSection(item)}
              >
                {item === "facility"
                  ? "Facility view"
                  : item === "activity"
                    ? "Business activity"
                    : "Infrastructure"}
              </button>
            ))}
          </nav>
        )}
        <p className="sidebar-note">
          Independent projection
          <br />
          {identity?.identity.scopes.includes("runs:control") &&
          !!twin?.controls.length
            ? "Configured controls"
            : "Read-only access"}
          <br />
          Simulation data only
        </p>
      </aside>
      <main>
        <header>
          <span>
            {auth ? identity?.identity.username : "Digital twin"}
            {auth && " / Live sources"}
          </span>
          {auth && (
            <button
              onClick={() => {
                setAuth("");
                setTwin(null);
                setIdentity(null);
                setSelected("");
                setRecord(null);
                setError("");
                setLost(false);
              }}
            >
              Sign out
            </button>
          )}
        </header>
        {!auth ? (
          <section className="login">
            <h1>Observe the facility.</h1>
            <p>
              Sign in to view production, inventory, transport and fulfilment
              from configured simulators.
            </p>
            <form onSubmit={login}>
              <label>
                Username
                <input
                  name="username"
                  autoComplete="username"
                  required
                  defaultValue="twin-operator"
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
            {error && <p role="alert">{error}</p>}
          </section>
        ) : (
          <>
            <div className="title-row">
              <div>
                <p className="eyebrow">
                  {section === "facility"
                    ? "Observed operations"
                    : section === "activity"
                      ? "Source records"
                      : "Independent source health"}
                </p>
                <h1>
                  {section === "facility"
                    ? "Facility overview"
                    : section === "activity"
                      ? "Business activity"
                      : "Infrastructure"}
                </h1>
              </div>
              <span className="badge">
                {lost
                  ? "Connection lost"
                  : twin
                    ? "Live · revision " + twin.revision
                    : "Connecting"}
              </span>
            </div>
            {lost && (
              <p className="alert" role="alert">
                Twin connection lost. Last observed data is retained; positions
                are frozen.
              </p>
            )}
            <div className="alignment">
              <span>
                {twin?.aligned
                  ? `Aligned committed watermark ${time(twin.aligned.committed)}`
                  : "No shared timeline"}
              </span>
              <span>Not an atomic federation snapshot.</span>
            </div>
            {identity?.identity.scopes.includes("runs:control") &&
              !!twin?.controls.length && (
                <section className="panel">
                  <h2>Configured controls</h2>
                  <p>
                    Local hold applies to one source. A global pause requires
                    explicit federation acknowledgement.
                  </p>
                  <div className="configured-controls">
                    {twin.controls.map((target) => (
                      <div key={target.name}>
                        <p>
                          {target.label} · {target.scope}
                        </p>
                        {target.actions.map((action) => {
                          const source = twin.sources.find(
                            (s) => s.name === target.source,
                          );
                          return (
                            <button
                              key={action}
                              disabled={
                                busy ||
                                lost ||
                                (!!pendingControl &&
                                  (pendingControl.target.name !== target.name ||
                                    pendingControl.action !== action)) ||
                                (!pendingControl &&
                                  target.scope === "local" &&
                                  (!source?.connected ||
                                    source.stale ||
                                    !source.status))
                              }
                              onClick={() => void control(target, action)}
                            >
                              {target.scope === "local"
                                ? action === "hold"
                                  ? "Local hold"
                                  : "Local resume"
                                : action === "pause" || action === "hold"
                                  ? "Request global pause"
                                  : "Request global resume"}
                            </button>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                  {controlMessage && <p role="status">{controlMessage}</p>}
                  {pendingControl && (
                    <div className="pending-control">
                      <p className="note">
                        Pending {pendingControl.target.label} /{" "}
                        {pendingControl.action}. Other control actions wait for
                        acknowledgement or rejection.
                      </p>
                      <code>{pendingControl.key}</code>
                      <button
                        disabled={busy || lost}
                        onClick={() =>
                          void control(
                            pendingControl.target,
                            pendingControl.action,
                          )
                        }
                      >
                        Retry pending control
                      </button>
                    </div>
                  )}
                </section>
              )}
            {!twin ? (
              <section className="empty">
                <h2>{lost ? "Twin unavailable" : "Waiting for source data"}</h2>
                <p>
                  {lost
                    ? "The observer will retry automatically."
                    : "Connecting to the durable Twin projection."}
                </p>
              </section>
            ) : !twin.sources.length ? (
              <section className="empty">
                <h2>No sources configured</h2>
                <p>
                  The Twin runs independently. Configure source APIs to observe
                  business operations. Stock, production and delivery state are
                  unavailable.
                </p>
              </section>
            ) : (
              <>
                {section === "facility" && (
                  <>
                    <div className="workspace">
                      <section
                        className="floor-panel"
                        aria-label="Facility schematic"
                      >
                        <div className="section-heading">
                          <h2>3D facility</h2>
                          <span>Catalog coordinates · metres</span>
                        </div>
                        <Facility3D
                          entities={all}
                          units={twin.handling?.units}
                          fleet={twin.fleet}
                          movements={twin.events.filter(event=>event.id.startsWith(event.source+':unit-movement:')&&(twin.handling?.units??[]).some(unit=>unit.id===event.payload.unit_id&&unit.run_id===event.run_id&&unit.epoch===event.epoch&&unit.status==='confirmed')).map(event=>({...event.payload,source:event.source,id:event.id}) as unknown as import('./journeys').Movement)}
                          sources={twin.sources}
                          selected={selected}
                          choose={choose}
                          lost={lost}
                        />
                        <div className="floor-key">
                          <span>Production cells</span>
                          <span>Storage racks</span>
                          <span>Vehicles</span>
                          <span>Loading bays</span>
                        </div>
                        {!!twin.handling?.unsupported_sources.length&&<p className="note">Handling data unavailable: {twin.handling.unsupported_sources.join(', ')}</p>}
                        <p className="note">
                          Units use recorded catalog positions. Empty slots are
                          facility capacity, not stock. Unknown or disputed
                          placements remain in the asset list without a 3D position.
                        </p>
                        <details className="asset-list">
                          <summary>All {all.length} source assets</summary>
                          {all.map((asset) => (
                            <button
                              key={asset.key}
                              onClick={() => choose(asset)}
                            >
                              {asset.kind} · {asset.label}
                            </button>
                          ))}
                        </details>
                      </section>
                      <section
                        className="detail-panel"
                        tabIndex={0}
                        aria-label="Selection details"
                      >
                        {entity ? (
                          <>
                            <div className="section-heading">
                              <h2>{entity.label}</h2>
                              <button
                                onClick={() => {
                                  setSelected("");
                                  setRecord(null);
                                }}
                              >
                                Clear
                              </button>
                            </div>
                            <p className="eyebrow">
                              {entity.kind} ·{" "}
                              {names[entity.source.name] ?? entity.source.name}
                            </p>
                            <span className="badge">
                              {lost ? "Connection lost" : health(entity.source)}
                            </span>
                            {selectedUnit ? <HandlingInspector unit={selectedUnit} units={twin.handling?.units??[]} sources={twin.sources} events={twin.events} lost={lost} choose={unit=>choose({key:`unit:${unit.run_id}:${unit.epoch}:${unit.id}`})}/> : <>
                            <Record row={detail ?? {}} />
                            <h3>Related records</h3>
                            {entity.related.length ? (
                              entity.related.map((r, i) => (
                                <button
                                  className="record-button"
                                  key={str(r.id ?? r.sku ?? i)}
                                  aria-label={
                                    "Inspect " + str(r.id ?? r.sku ?? i)
                                  }
                                  onClick={() => setRecord(r)}
                                >
                                  <span>{str(r.id ?? r.sku)}</span>
                                  <span>
                                    {str(r.status ?? r.available ?? r.quantity)}
                                  </span>
                                </button>
                              ))
                            ) : (
                              <p className="note">
                                No related records in this snapshot.
                              </p>
                            )}
                            <h3>Correlated business records</h3>
                            {correlatedRecords.length ? (
                              correlatedRecords.map(
                                ({ source, kind, row }, i) => (
                                  <p
                                    className="note"
                                    key={source.name + ":" + kind + ":" + i}
                                  >
                                    {names[source.name] ?? source.name} · {kind}
                                    <br />
                                    {str(row.id)}
                                    <br />
                                    {str(row.status)} · Quantity{" "}
                                    {str(
                                      row.quantity ??
                                        (Array.isArray(row.lines)
                                          ? rows(row.lines).reduce(
                                              (total, line) =>
                                                total +
                                                (typeof line.quantity ===
                                                "number"
                                                  ? line.quantity
                                                  : 0),
                                              0,
                                            )
                                          : null),
                                    )}
                                  </p>
                                ),
                              )
                            ) : (
                              <p className="note">
                                No correlated records in received snapshots.
                              </p>
                            )}
                            <h3>Correlated event history</h3>
                            <History events={relatedEvents} />
                            </>}
                          </>
                        ) : (
                          <>
                            <p className="eyebrow">Inspect operations</p>
                            <h2>Select an asset</h2>
                            <p>
                              Choose a handling unit or source asset to inspect
                              its recorded state and source history.
                            </p>
                            <div className="selection-hint">
                              <strong>{all.length}</strong>
                              <span>assets in received snapshots</span>
                            </div>
                            <p className="note">
                              Unavailable departments are not populated with
                              sample data.
                            </p>
                          </>
                        )}
                      </section>
                    </div>
                    <section
                      className="source-strip"
                      aria-label="Source watermarks"
                    >
                      {twin.sources.map((source) => (
                        <SourcePanel
                          key={source.name}
                          source={source}
                          lost={lost}
                        />
                      ))}
                    </section>
                  </>
                )}
                {section === "activity" && (
                  <>
                    <section className="panel">
                      <div className="section-heading">
                        <h2>Observed business records</h2>
                        <label className="search">
                          Search records
                          <input
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                            placeholder="ID, SKU, status or correlation"
                          />
                        </label>
                      </div>
                      <div className="table-wrap">
                        <table>
                          <thead>
                            <tr>
                              <th>Source / record</th>
                              <th>Reference</th>
                              <th>State</th>
                              <th>Quantity</th>
                              <th>Correlation</th>
                            </tr>
                          </thead>
                          <tbody>
                            {ledger.map(({ source, kind, row }, i) => (
                              <tr
                                key={`${source.name}:${kind}:${str(row.id ?? i)}`}
                              >
                                <td>
                                  {names[source.name] ?? source.name}
                                  <small>
                                    {kind} · {health(source)}
                                  </small>
                                </td>
                                <td>{str(row.id ?? row.sku ?? row.code)}</td>
                                <td>{str(row.status ?? row.kind)}</td>
                                <td>{str(row.quantity ?? row.on_hand)}</td>
                                <td>{str(row.correlation_id)}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {!ledger.length && (
                          <p>No matching records in received snapshots.</p>
                        )}
                      </div>
                    </section>
                    <section className="panel">
                      <h2>Current-run event history</h2>
                      <History events={relatedEvents} />
                    </section>
                  </>
                )}
                {section === "infrastructure" && (
                  <>
                    <section className="source-strip">
                      {twin.sources.map((source) => (
                        <SourcePanel
                          key={source.name}
                          source={source}
                          lost={lost}
                          expanded
                        />
                      ))}
                    </section>
                    <section className="panel">
                      <h2>Twin processes</h2>
                      {twin.heartbeats?.length ? (
                        twin.heartbeats.map((h) => (
                          <p key={h.role}>
                            {h.role} ·{" "}
                            {!lost && h.healthy ? "Healthy" : "Unavailable"}
                          </p>
                        ))
                      ) : (
                        <p>Process health is unavailable.</p>
                      )}
                      <p>
                        Read-only observer. Local holds belong to individual
                        sources and do not acknowledge a federation-wide pause.
                      </p>
                    </section>
                  </>
                )}
              </>
            )}
            <footer>
              Digital twin · Independent Flask / React website ·{" "}
              {identity?.identity.scopes.includes("runs:control") &&
              !!twin?.controls.length
                ? "Configured controls"
                : "Read-only"}
            </footer>
          </>
        )}
      </main>
    </div>
  );
}
function SourcePanel({
  source,
  lost,
  expanded = false,
}: {
  source: Source;
  lost: boolean;
  expanded?: boolean;
}) {
  const run = source.status?.run;
  const website = safeWebsite(source.website_url);
  return (
    <article className="source-panel">
      <div className="section-heading">
        <h2>{names[source.name] ?? source.name}</h2>
        <span
          className={
            "badge " +
            (source.stale || !source.connected || lost ? "warning" : "")
          }
        >
          {lost ? "Connection lost" : health(source)}
        </span>
      </div>
      <div className="source-clock">
        <strong>{calendar(run)}</strong>
        <span>
          {run?.scenario?.time_zone ?? "Timezone unavailable"} ·{" "}
          {typeof run?.speed === "number"
            ? `${run.speed}× speed`
            : "Speed unavailable"}
        </span>
      </div>
      <p>
        {run?.state === "held"
          ? "Local hold"
          : run?.blocked_reason
            ? "Stalled"
            : (run?.state ?? "Run unavailable")}
      </p>
      {run?.blocked_reason && <p className="warning">{run.blocked_reason}</p>}
      <dl className="watermarks">
        <div>
          <dt>Requested</dt>
          <dd>{time(run?.requested)}</dd>
        </div>
        <div>
          <dt>Granted</dt>
          <dd>{time(run?.granted)}</dd>
        </div>
        <div>
          <dt>Committed</dt>
          <dd>{time(run?.committed)}</dd>
        </div>
      </dl>
      <p className="note">
        Last success
        <br />
        {date(source.last_success_at)}
      </p>
      {!source.snapshot && <p className="warning">Snapshot unavailable</p>}
      {source.error && (
        <p className="warning">
          Source observation failed. Check source connectivity.
        </p>
      )}
      {expanded && (
        <dl>
          <dt>Run ID</dt>
          <dd>{run?.id ?? "Unavailable"}</dd>
          <dt>Epoch</dt>
          <dd>{run?.epoch ?? "Unavailable"}</dd>
          <dt>Cursor</dt>
          <dd>{source.cursor ?? "Unavailable"}</dd>
          <dt>Last checked</dt>
          <dd>{date(source.observed_at)}</dd>
        </dl>
      )}
      {expanded && <SourceHealth source={source} lost={lost} />}
      {website && (
        <a href={website} target="_blank" rel="noopener noreferrer">
          Open {names[source.name] ?? source.name} website
        </a>
      )}
    </article>
  );
}
function SourceHealth({ source, lost }: { source: Source; lost: boolean }) {
  const unavailable = lost || source.stale || !source.connected;
  const observed = source.health;
  const roles = [
    ...new Set([
      "worker",
      "controller",
      ...(observed?.heartbeats ?? []).map((h) => h.role),
    ]),
  ];
  const broker = observed?.broker;
  const brokerHealthy = typeof broker === "boolean" ? broker : broker?.healthy;
  return (
    <section aria-label={`${source.name} infrastructure health`}>
      <h3>Processes and backlog</h3>
      {roles.map((role) => {
        const heartbeat = observed?.heartbeats?.find((h) => h.role === role);
        return (
          <p className="note" key={role}>
            {role} ·{" "}
            {unavailable
              ? "Unavailable"
              : heartbeat
                ? heartbeat.healthy
                  ? "Healthy"
                  : "Unavailable"
                : "Unknown"}
            {heartbeat?.seen_at && (
              <small>
                <br />
                Last seen {date(heartbeat.seen_at)}
              </small>
            )}
          </p>
        );
      })}
      <p className="note">
        Pending jobs:{" "}
        {!unavailable && typeof observed?.pending_jobs === "number"
          ? observed.pending_jobs
          : "Unavailable"}
      </p>
      <p className="note">
        Dead letters:{" "}
        {!unavailable && typeof observed?.dead_letters === "number"
          ? observed.dead_letters
          : "Unavailable"}
      </p>
      <p className="note">
        {!unavailable && typeof observed?.ready === "boolean"
          ? observed.ready
            ? "Ready"
            : "Not ready"
          : "Readiness unavailable"}
      </p>
      <p className="note">
        {!unavailable && typeof brokerHealthy === "boolean"
          ? `Broker · ${brokerHealthy ? "Healthy" : "Unavailable"}`
          : "Broker health unavailable"}
      </p>
    </section>
  );
}
function Record({ row }: { row: Row }) {
  return (
    <dl className="record-fields">
      {Object.entries(row).map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{str(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
function History({ events }: { events: Event[] }) {
  return events.length ? (
    <ol className="history">
      {events.map((e) => (
        <li key={e.source + ":" + e.id}>
          <span>
            {time(e.simulation_time)} · {e.source}
          </span>
          <strong>
            {str(
              e.payload.action ??
                e.payload.kind ??
                e.payload.status ??
                "Observed event",
            )}
          </strong>
          <small>{e.correlation_id ?? e.id}</small>
          <details>
            <summary>Event payload</summary>
            <pre>{JSON.stringify(e.payload, null, 2)}</pre>
          </details>
        </li>
      ))}
    </ol>
  ) : (
    <p className="note">No matching events in the current run and epoch.</p>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
