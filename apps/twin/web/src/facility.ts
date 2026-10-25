import fixedCatalog from '../../../../contracts/handling/v1/facility.json' with {type: 'json'};

export type Vec3 = [number, number, number];
export type Endpoint = {
  id: string; owner: string; kind: string; compatible: string[]; capacity: number;
  position: Vec3; access: Vec3;
};
export type RecordedUnit = {
  id: string; barcode: string; run_id: string; epoch: string;
  category: string; contents: {sku: string; quantity: number}[];
  owner: string | null; state: string | null; status: string; position: string | null;
  custody_generation?:number|null; conflicts?:Record<string,unknown>[];
  connected: boolean; observations: {source: string; unit: Record<string, unknown>}[];
};
export const facility = fixedCatalog as unknown as {
  version: number; locations: Endpoint[]; lanes: {id: string; from: Vec3; to: Vec3}[];
};
const endpoints = new Map(facility.locations.map(location => [location.id, location]));
export function endpoint(id: string | null): Endpoint | null {
  return id === null ? null : endpoints.get(id) ?? null;
}
export function rackGroups() {
  const groups = new Map<string, Endpoint[]>();
  for (const location of facility.locations) {
    if (location.kind !== 'shelf') continue;
    const id = location.id.split('.').slice(0, 3).join('.');
    groups.set(id, [...(groups.get(id) ?? []), location]);
  }
  return [...groups].map(([id, slots]) => ({id, slots,
    elevations: [...new Set(slots.map(slot => slot.position[1]))].sort((a, b) => a - b)}));
}
export function recordedPlacement(unit: Pick<RecordedUnit, 'status' | 'state' | 'position'>): Vec3 | null {
  if (unit.status !== 'confirmed' || !['available', 'reserved'].includes(unit.state ?? '')) return null;
  return endpoint(unit.position)?.position ?? null;
}
export function visibleUnits<T extends Pick<RecordedUnit, 'status' | 'state' | 'position'>>(units: T[]): T[] {
  return units.filter(unit => recordedPlacement(unit) !== null);
}

export function truckGroups() {
  const groups = new Map<string, Endpoint[]>();
  for (const location of facility.locations) {
    if (location.kind !== 'truck') continue;
    const id = location.id.split('.').slice(0,-1).join('.');
    groups.set(id,[...(groups.get(id) ?? []),location]);
  }
  return [...groups].map(([id,slots]) => ({id,slots}));
}
