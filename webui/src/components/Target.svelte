<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type ApSnap, type AttackSpec, type Capture } from '../lib/api';
  import { attack } from '../lib/stores';
  import { onEvent } from '../lib/socket';
  import { encClass, encIcon } from '../lib/format';
  import LogView from './LogView.svelte';
  import Sparkline from './Sparkline.svelte';

  interface Props {
    bssid: string;
    now: number;
  }
  let { bssid, now }: Props = $props();

  let ap: ApSnap | null = $state(null);
  let attacks: AttackSpec[] = $state([]);
  let captures: Capture[] = $state([]);
  let error: string | null = $state(null);
  let busyKind: string | null = $state(null);
  let hist: Record<'beacon' | 'data' | 'inject' | 'deauth', number[]> = $state({
    beacon: [], data: [], inject: [], deauth: []
  });

  const SERIES: { key: 'beacon' | 'data' | 'inject' | 'deauth'; label: string; token: string }[] = [
    { key: 'beacon', label: 'beacon', token: '--secondary' },
    { key: 'data', label: 'data', token: '--primary' },
    { key: 'inject', label: 'inject', token: '--accent' },
    { key: 'deauth', label: 'deauth', token: '--attack' }
  ];

  async function load() {
    try {
      const d = await api.ap(bssid);
      ap = d.ap;
      attacks = d.attacks;
      captures = d.captures;
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  onMount(() => {
    load();
    const timer = setInterval(load, 5000);
    const off = onEvent((event) => {
      if (event.topic !== 'scan.tick') return;
      const payload = event.payload as { rates?: Record<string, Record<string, number>> };
      const r = payload.rates?.[bssid];
      if (!r) return;
      for (const { key } of SERIES) {
        const v = Number(r[key] ?? 0);
        hist[key] = [...hist[key].slice(-89), v];
      }
    });
    return () => {
      clearInterval(timer);
      off();
    };
  });

  const live = $derived($attack && $attack.bssid.toLowerCase() === bssid.toLowerCase() ? $attack : null);

  async function start(kind: string) {
    busyKind = kind;
    error = null;
    try {
      await api.startAttack(kind, bssid);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      busyKind = null;
    }
  }

  async function stop() {
    try {
      await api.stopAttack();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }
</script>

<p><a href="#/">← scanner</a></p>

{#if error}
  <div class="error">{error}</div>
{/if}

{#if ap}
  <h2>{ap.ssid ?? '<hidden>'} <small class="mono">{ap.bssid} · CH{ap.channel}</small></h2>
  <p>
    <span class="enc {encClass(ap.encryption)}">{encIcon(ap.encryption)} {ap.encryption}</span>
    · {ap.signal} dBm · {ap.clients.length} clients · {ap.beacons} beacons
  </p>

  <h3>Packet rates <small>(packets/s, live)</small></h3>
  <div class="sparks">
    {#each SERIES as s (s.key)}
      <section class="spark">
        <header>
          <span style="color: var({s.token})">●</span> {s.label}
          <span class="val">{hist[s.key].length ? hist[s.key][hist[s.key].length - 1].toFixed(1) : '—'}/s</span>
        </header>
        <Sparkline series={[hist[s.key]]} tokens={[s.token]} />
      </section>
    {/each}
  </div>

  <h3>Attacks</h3>
  <div class="btnrow">
    {#each attacks as spec (spec.kind)}
      {@const running = live && live.kind === spec.kind}
      <button
        class="attack-btn"
        class:running={!!running}
        disabled={!!spec.blocked || (!!live && !running) || busyKind === spec.kind}
        title={spec.blocked ?? spec.label}
        onclick={() => (running ? stop() : start(spec.kind))}
      >
        {running ? `Stop ${spec.label}` : spec.label}
      </button>
    {/each}
    {#if live}
      <button class="stopall" onclick={stop}>Stop all</button>
    {/if}
  </div>
  {#if attacks.length === 0}
    <div class="empty">○ No applicable attacks for this AP.</div>
  {/if}

  <h3>Log</h3>
  <LogView />

  <h3>Captures ({captures.length})</h3>
  {#if captures.length === 0}
    <div class="empty">○ Nothing captured yet.</div>
  {:else}
    <table class="scan">
      <thead><tr><th>Type</th><th>Time</th><th>Records</th><th>Value</th></tr></thead>
      <tbody>
        {#each captures as c (c.path)}
          <tr><td>{c.type}</td><td>{new Date(c.timestamp * 1000).toLocaleString()}</td>
            <td class="num">{c.record_count}</td><td>{c.has_value ? '✓ saved' : ''}</td></tr>
        {/each}
      </tbody>
    </table>
  {/if}
{:else if !error}
  <div class="empty">○ Loading target…</div>
{/if}
