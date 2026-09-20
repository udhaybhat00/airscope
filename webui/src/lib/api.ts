/** Shared API shapes (mirror exports.ApSnap / health payloads). */
export interface ClientSnap {
  mac: string;
  signal: number;
  packets: number;
}

export interface ApSnap {
  bssid: string;
  ssid: string | null;
  channel: number;
  signal: number;
  encryption: string;
  akms: string[];
  beacons: number;
  first_seen: number;
  last_seen: number;
  clients: ClientSnap[];
}

export interface Health {
  name: string;
  version: string;
  engine: string;
}

export interface Device {
  vid: number;
  pid: number;
  chipset: string;
  vendor: string | null;
  product: string | null;
  bus: number | null;
  address: number | null;
  attached: boolean;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

async function send<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined
  });
  const data = (await res.json().catch(() => ({}))) as T & { detail?: string };
  if (!res.ok) throw new Error(data.detail || `${path}: ${res.status}`);
  return data;
}

export interface AttackSpec {
  kind: string;
  label: string;
  blocked: string | null;
}

export interface Capture {
  type: string;
  path: string;
  timestamp: number;
  ssid: string | null;
  record_count: number;
  has_value: boolean;
}

export interface Attack {
  id: string;
  kind: string;
  bssid: string;
  ssid: string | null;
  started: number;
  state: string;
}

export interface CrackJob {
  id: string;
  path: string;
  bssid: string;
  ssid: string | null;
  started: number;
  state: string;
}

export interface BatchStep {
  bssid: string;
  ssid: string | null;
  kind: string;
  timeout: number;
}

export interface StepResult {
  bssid: string;
  ssid: string | null;
  kind: string;
  outcome: string;
  detail: string;
  seconds: number;
}

export interface BatchJob {
  id: string;
  started: number;
  state: string;
  steps: BatchStep[];
  skipped: StepResult[];
  results: StepResult[];
  solved: number;
}

export const api = {
  health: () => get<Health>('/api/health'),
  devices: () => get<{ devices: Device[] }>('/api/devices'),
  aps: () => get<{ aps: ApSnap[]; at: number }>('/api/aps'),
  ap: (bssid: string) =>
    get<{ ap: ApSnap | null; attacks: AttackSpec[]; captures: Capture[] }>(
      `/api/aps/${encodeURIComponent(bssid)}`
    ),
  startAttack: (kind: string, bssid: string) =>
    send<Attack>('POST', `/api/attacks/${kind}`, { bssid }),
  currentAttack: () => get<{ attack: Attack | null }>('/api/attacks/current'),
  stopAttack: () => send<{ stopped: boolean }>('DELETE', '/api/attacks/current'),
  vault: () =>
    get<{ aps: { bssid: string; ssid: string | null; captures: Capture[] }[] }>('/api/vault'),
  deleteCapture: (path: string) =>
    send<{ deleted: boolean }>('DELETE', `/api/vault/file?path=${encodeURIComponent(path)}`),
  downloadUrl: (path: string) => `/api/vault/file?path=${encodeURIComponent(path)}`,
  startCrack: (path: string, wordlist: string) =>
    send<CrackJob>('POST', '/api/crack', { path, wordlist }),
  crackJob: (id: string) => get<CrackJob>(`/api/jobs/${id}`),
  startBatch: (bssids: string[]) =>
    send<BatchJob>('POST', '/api/batch', { bssids }),
  batchJob: (id: string) => get<BatchJob>(`/api/batch/${id}`),
  stopBatch: (id: string) => send<{ stopped: boolean }>('DELETE', `/api/batch/${id}`),
  setScanning: (on: boolean) =>
    send<{ scanning: boolean }>('POST', `/api/scan/${on ? 'start' : 'stop'}`),
  exportUrl: (kind: string) => `/api/exports/${kind}`
};
