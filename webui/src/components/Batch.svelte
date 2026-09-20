<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type BatchJob } from '../lib/api';
  import { batches, batchLines } from '../lib/stores';
  import { plainEnglish } from '../lib/log_translate';

  interface Props {
    id: string;
  }
  let { id }: Props = $props();

  let job: BatchJob | null = $state(null);
  let error: string | null = $state(null);

  async function load() {
    try {
      const j = await api.batchJob(id);
      job = j;
      batches.update((m) => new Map(m.set(id, j)));
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  onMount(() => {
    load();
    const timer = setInterval(load, 2000);
    return () => clearInterval(timer);
  });

  async function stop() {
    try {
      await api.stopBatch(id);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  const live = $derived($batches.get(id) ?? job);
  const results = $derived(live?.results ?? []);
  const doneCount = $derived(results.length);
  const total = $derived(live?.steps.length ?? 0);
  const progressPct = $derived(total > 0 ? Math.round((doneCount / total) * 100) : 0);

  function attackLabel(kind: string): string {
    if (kind === 'deauth') return 'Deauth Attack';
    if (kind === 'pmkid') return 'PMKID Harvest';
    if (kind === 'eviltwin') return 'Evil Twin';
    if (kind === 'wps-pin') return 'WPS PIN Attack';
    return kind;
  }

  function skipReason(detail: string): string {
    const lower = (detail || '').toLowerCase();
    if (lower.includes('wpa3')) return 'WPA3 only — no handshake attack applicable';
    if (lower.includes('pmf')) return 'Protected Management Frames — deauth blocked';
    if (lower.includes('wps')) return 'No WPS setup vulnerability found';
    if (lower.includes('open')) return 'Open network — no password to capture';
    return detail;
  }
</script>

<nav class="breadcrumb"><a href="#/">📡 Scanner</a> <span class="sep">→</span> <span>Auto Attack</span></nav>
<h2>⚡ Auto Attack <small class="mono">{id}</small></h2>

{#if error}
  <div class="error">{error}</div>
{/if}

{#if live}
  <div class="batch-progress">
    <div class="progress-bar" style="width: {progressPct}%"></div>
    <span class="progress-text">{doneCount} / {total} steps ({progressPct}%)</span>
  </div>

  <p>
    {#if live.state === 'running'}
      <span class="dot ok">●</span> Running {doneCount}/{total} steps
      <button class="stopall" onclick={stop}>Stop after this step</button>
    {:else}
      <span class="dot">●</span> Done — {live.solved} solved/captured over {total} steps
    {/if}
  </p>

  {#if live.skipped.length > 0}
    <h3>Skipped</h3>
    <table class="scan">
      <tbody>
        {#each live.skipped as s (s.bssid + s.kind)}
          <tr><td>{s.ssid ?? s.bssid}</td><td class="mono">{s.bssid}</td><td>{skipReason(s.detail)}</td></tr>
        {/each}
      </tbody>
    </table>
  {/if}

  <h3>Steps</h3>
  <table class="scan">
    <thead><tr><th>#</th><th>Target</th><th>Attack</th><th>Outcome</th><th>Detail</th></tr></thead>
    <tbody>
      {#each live.steps as s, i (s.bssid + s.kind)}
        {@const r = results.find((x) => x.bssid === s.bssid && x.kind === s.kind)}
        <tr>
          <td class="num">{i + 1}</td>
          <td>{s.ssid ?? s.bssid}</td>
          <td>{attackLabel(s.kind)}</td>
          {#if r}
            <td class={r.outcome === 'timeout' ? 'stale' : 'ok'}>{r.outcome}</td>
            <td>{r.detail}</td>
          {:else}
            <td><span class="dot ok">●</span> Running…</td>
            <td></td>
          {/if}
        </tr>
      {/each}
    </tbody>
  </table>

  <h3>Log</h3>
  <div class="log">
    {#each $batchLines.slice(-100) as line}
      <div>{plainEnglish(line)}</div>
    {:else}
      <div class="empty-inline">Waiting for step output…</div>
    {/each}
  </div>
{:else}
  <div class="empty">Loading batch…</div>
{/if}
