export type SceneRow = Record<string, unknown>;
export type SceneEntity = {
  key: string; kind: string; label: string; row: SceneRow; related: SceneRow[];
  source: {name: string; connected: boolean; stale: boolean;
    status: {run: {id: string; epoch: string; state: string; granted: number}} | null};
};
export function vehicleState(entity: Pick<SceneEntity,'key'|'kind'|'source'|'related'>, lost: boolean, positions: Map<string,number>) {
  const run = entity.source.status?.run;
  const frozen = lost || !entity.source.connected || entity.source.stale || run?.state !== 'running';
  const transfer = entity.related.find(row => row.status === 'in_transit');
  const estimated = entity.kind === 'vehicle' && !!transfer && typeof transfer.departed_at === 'number' &&
    typeof transfer.planned_eta === 'number' && transfer.planned_eta > transfer.departed_at;
  if (!estimated || !transfer) return {estimated: false, frozen, awaitingConfirmation: false, progress: 0};
  const departure = transfer.departed_at as number, arrival = transfer.planned_eta as number;
  const grant = run?.granted ?? departure;
  const fraction = Math.max(0, Math.min(1, (grant - departure) / (arrival - departure)));
  const key = `${entity.key}:${run?.id}:${run?.epoch}:${String(transfer.id)}`;
  const progress = frozen ? positions.get(key) ?? fraction : fraction;
  if (!frozen) positions.set(key, progress);
  return {estimated, frozen, progress, awaitingConfirmation: grant >= arrival};
}
