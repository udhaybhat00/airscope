import { writable } from 'svelte/store';
import type { ApSnap, Attack, CrackJob, Health } from './api';

export type ConnStatus = 'connecting' | 'live' | 'reconnecting';

/** Socket state for the status strip. */
export const status = writable<ConnStatus>('connecting');

/** Latest AP snapshot keyed by BSSID (replaced wholesale per tick). */
export const aps = writable<Map<string, ApSnap>>(new Map());

/** Backend health for the header. */
export const health = writable<Health | null>(null);

/** Channel hopping live (false after POST /api/scan/stop). */
export const scanning = writable<boolean>(true);

/** Command palette open state. */
export const paletteOpen = writable<boolean>(false);

/** Live attack record (null when the radio is free). */
export const attack = writable<Attack | null>(null);

/** Attack log lines for the target view. */
export const attackLines = writable<string[]>([]);

/** Bumped on vault.changed / capture.saved so Vault refetches. */
export const vaultVersion = writable(0);

/** Crack jobs by id (progress events merge in). */
export const cracks = writable<
  Map<string, { job: CrackJob; tested: number; total: number; speed: string; psk?: string }>
>(new Map());

/** Marked BSSIDs for the batch queue (scanner checkboxes). */
export const marked = writable<Set<string>>(new Set());

/** Live batch jobs by id (step events merge in). */
export const batches = writable<Map<string, import('./api').BatchJob>>(new Map());

/** Batch log lines for the open batch view. */
export const batchLines = writable<string[]>([]);
