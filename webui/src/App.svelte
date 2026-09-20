<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Health } from './lib/api';
  import { aps, health, marked, paletteOpen, status } from './lib/stores';
  import { startSocket, stopSocket } from './lib/socket';
  import ApTable from './components/ApTable.svelte';
  import Target from './components/Target.svelte';
  import Vault from './components/Vault.svelte';
  import Batch from './components/Batch.svelte';
  import Reports from './components/Reports.svelte';
  import Devices from './components/Devices.svelte';
  import CommandPalette from './components/CommandPalette.svelte';

  let tickAt: number | null = $state(null);
  let now = $state(Date.now());
  let route: string = $state(location.hash || '#/');
  let batchError: string | null = $state(null);

  function syncRoute() {
    route = location.hash || '#/';
  }

  onMount(() => {
    api.health().then((h: Health) => health.set(h)).catch(() => {});
    api.aps().then((r) => {
      aps.set(new Map(r.aps.map((a) => [a.bssid, a])));
      tickAt = r.at;
    }).catch(() => {});
    const onkey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        paletteOpen.update((v) => !v);
      }
    };
    window.addEventListener('keydown', onkey);
    window.addEventListener('hashchange', syncRoute);
    startSocket();
    const clock = setInterval(() => (now = Date.now()), 1000);
    const ticker = setInterval(async () => {
      try {
        const r = await api.aps();
        tickAt = r.at;
      } catch { /* socket owns liveness; polling only stamps the tick */ }
    }, 5000);
    return () => {
      window.removeEventListener('keydown', onkey);
      window.removeEventListener('hashchange', syncRoute);
      stopSocket();
      clearInterval(clock);
      clearInterval(ticker);
    };
  });

  const rows = $derived([...$aps.values()]);
  const nClients = $derived(rows.reduce((n, a) => n + a.clients.length, 0));

  const targetBssid = $derived(
    route.startsWith('#/target/') ? decodeURIComponent(route.slice('#/target/'.length)) : null
  );
  const showVault = $derived(route === '#/vault');
  const showReports = $derived(route === '#/reports');
  const showDevices = $derived(route === '#/devices');
  const isDemo = $derived($health?.engine === 'demo');
  const batchId = $derived(
    route.startsWith('#/batch/') ? decodeURIComponent(route.slice('#/batch/'.length)) : null
  );

  async function startBatch() {
    batchError = null;
    try {
      const job = await api.startBatch([...$marked]);
      marked.set(new Set());
      location.hash = `#/batch/${job.id}`;
    } catch (e) {
      batchError = e instanceof Error ? e.message : String(e);
    }
  }
</script>

<header class="topbar">
  <span class="brand"><a href="#/">airscope</a> <small>v{$health?.version ?? '…'}</small></span>
  <nav>
    <a href="#/" class:active={route === '#/'}>scanner</a>
    <a href="#/devices" class:active={showDevices}>devices</a>
    <a href="#/vault" class:active={showVault}>vault</a>
    <a href="#/reports" class:active={showReports}>reports</a>
  </nav>
  <span class="context">{$health?.engine ?? '…'}</span>
  <span class="spacer"></span>
  <button class="kbd-hint" onclick={() => paletteOpen.set(true)} title="Command palette">Ctrl+K</button>
  <span class="dot {$status}">●</span>
  <span class="context">{$status}</span>
</header>

<main>
  {#if isDemo}
    <div class="demobanner" role="note">
      ▲ DEMO MODE — simulated scan. No radio, no hardware, nothing here is real.
    </div>
  {/if}
  {#if targetBssid}
    {#key targetBssid}
      <Target bssid={targetBssid} {now} />
    {/key}
  {:else if showVault}
    <Vault />
  {:else if showReports}
    <Reports />
  {:else if showDevices}
    <Devices />
  {:else if batchId}
    <Batch id={batchId} />
  {:else}
    {#if batchError}
      <div class="error">{batchError}</div>
    {/if}
    {#if $marked.size > 0}
      <div class="batchbar">
        <span>{$marked.size} marked</span>
        <button class="attack-btn" onclick={startBatch}>Batch attack</button>
        <button class="btn" onclick={() => marked.set(new Set())}>Clear</button>
      </div>
    {/if}
    <ApTable aps={rows} {now} />
  {/if}
</main>

<CommandPalette />

<footer class="statusbar">
  <span class:ok={$status === 'live'} class:warn={$status !== 'live'}>
    {$status === 'live' ? `● ${rows.length} APs · ${nClients} clients` : `○ ${$status}…`}
  </span>
  <span class="spacer"></span>
  <span>{tickAt ? `tick ${new Date(tickAt * 1000).toLocaleTimeString()}` : 'no ticks yet'}</span>
</footer>
