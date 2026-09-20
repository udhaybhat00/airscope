/** Event socket with backoff reconnect. Status drives the status strip:
 * connecting -> live -> reconnecting -> live, no manual refresh needed. */
import { aps, attack, attackLines, batchLines, batches, cracks, scanning, status, vaultVersion, type ConnStatus } from './stores';
import type { Attack, BatchJob, CrackJob } from './api';

export interface BusEvent {
  topic: string;
  payload: Record<string, unknown>;
}

type Handler = (event: BusEvent) => void;

const BACKOFF = [1000, 2000, 5000];
let ws: WebSocket | null = null;
let attempt = 0;
let wanted = false;
const handlers = new Set<Handler>();

export function onEvent(handler: Handler): () => void {
  handlers.add(handler);
  return () => handlers.delete(handler);
}

function url(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${location.host}/api/ws/events`;
}

function emit(statusValue: ConnStatus) {
  status.set(statusValue);
}

function connect() {
  if (!wanted) return;
  emit(attempt === 0 ? 'connecting' : 'reconnecting');
  try {
    ws = new WebSocket(url());
  } catch {
    return schedule();
  }
  ws.onopen = () => {
    attempt = 0;
    emit('live');
  };
  ws.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data) as BusEvent;
      route(event);
      handlers.forEach((h) => h(event));
    } catch {
      // A malformed frame must never kill the stream.
    }
  };
  ws.onclose = () => schedule();
  ws.onerror = () => ws?.close();
}

function schedule() {
  ws = null;
  if (!wanted) return;
  const delay = BACKOFF[Math.min(attempt, BACKOFF.length - 1)];
  attempt += 1;
  emit('reconnecting');
  setTimeout(connect, delay);
}

/** Built-in routing from bus topics into stores; pages add their own via onEvent. */
function route(event: BusEvent) {
  const p = event.payload as Record<string, unknown>;
  if (event.topic === 'scan.tick') {
    const list = (p.aps ?? []) as import('./api').ApSnap[];
    aps.set(new Map(list.map((a) => [a.bssid, a])));
    if (typeof p.scanning === 'boolean') scanning.set(p.scanning);
  } else if (event.topic === 'attack.log') {
    attackLines.update((lines) => [...lines.slice(-199), String(p.line ?? '')]);
  } else if (event.topic === 'attack.state') {
    if (p.state === 'started') {
      attack.set({
        id: String(p.id ?? ''), kind: String(p.kind ?? ''),
        bssid: String(p.bssid ?? ''), ssid: (p.ssid as string | null) ?? null,
        started: Number(p.started ?? 0), state: 'running'
      } as Attack);
      attackLines.set([]);
    } else if (p.state === 'finished' || p.state === 'stopped') {
      attack.set(null);
    }
  } else if (event.topic === 'vault.changed' || event.topic === 'capture.saved') {
    vaultVersion.update((v) => v + 1);
  } else if (event.topic === 'batch.started') {
    batches.update((m) => new Map(m.set(String(p.id ?? ''), {
      id: String(p.id ?? ''), started: 0, state: 'running',
      steps: [], skipped: [], results: [], solved: 0
    } as BatchJob)));
    batchLines.set([]);
  } else if (event.topic === 'batch.log') {
    batchLines.update((lines) => [...lines.slice(-199), String(p.line ?? '')]);
  } else if (event.topic === 'batch.step') {
    batches.update((m) => {
      const id = String(p.job_id ?? '');
      const job = m.get(id);
      if (job && p.result) {
        const r = p.result as BatchJob['results'][number];
        if (!job.results.some((x) => x.bssid === r.bssid && x.kind === r.kind)) {
          job.results = [...job.results, r];
        }
        return new Map(m.set(id, job));
      }
      return m;
    });
  } else if (event.topic === 'batch.done' || event.topic === 'batch.stopped') {
    batches.update((m) => {
      const id = String(p.id ?? p.job_id ?? '');
      const job = m.get(id);
      if (job) {
        job.state = 'done';
        return new Map(m.set(id, job));
      }
      return m;
    });
  } else if (event.topic === 'crack.progress') {
    cracks.update((m) => {
      const id = String(p.id ?? '');
      const cur = m.get(id) ?? {
        job: { id, path: '', bssid: '', ssid: null, started: 0, state: 'running' } as CrackJob,
        tested: 0, total: 0, speed: ''
      };
      cur.tested = Number(p.tested ?? 0);
      cur.total = Number(p.total ?? 0);
      cur.speed = String(p.speed ?? '');
      return new Map(m.set(id, cur));
    });
  } else if (event.topic === 'crack.done') {
    cracks.update((m) => {
      const id = String(p.id ?? '');
      const cur = m.get(id);
      if (cur) {
        cur.job.state = String(p.state ?? 'done');
        if (p.psk) cur.psk = String(p.psk);
        return new Map(m.set(id, cur));
      }
      return m;
    });
  }
}

export function startSocket() {
  if (wanted) return;
  wanted = true;
  attempt = 0;
  connect();
}

export function stopSocket() {
  wanted = false;
  ws?.close();
  ws = null;
}
