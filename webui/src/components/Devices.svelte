<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Device } from '../lib/api';

  let devices: Device[] = $state([]);
  let error: string | null = $state(null);

  async function load() {
    try {
      const d = await api.devices();
      devices = d.devices;
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  onMount(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  });

  function vidpid(d: Device): string {
    const h = (n: number) => n.toString(16).padStart(4, '0');
    return `${h(d.vid)}:${h(d.pid)}`;
  }
</script>

<h2>Devices</h2>

{#if error}
  <div class="error">{error}</div>
{/if}

{#if devices.length === 0}
  <div class="empty">
    <p>○ No supported USB adapters detected.</p>
    <p>
      airscope drives USB Wi-Fi cards directly over USB — it needs at least one
      adapter from the <strong>supported hardware list</strong>, plus a one-time
      driver setup (udev rules on Linux, WinUSB on Windows) done through the TUI.
    </p>
    <p>
      <a
        class="btn"
        href="https://github.com/udhaybhat00/airscope/blob/main/docs/SUPPORTED-HARDWARE.md"
        target="_blank"
        rel="noreferrer"
      >Supported hardware docs ↗</a>
    </p>
    <p class="hint">No hardware handy? Restart with <code>--demo</code> to explore the UI on a simulated scan.</p>
  </div>
{:else}
  <table class="scan">
    <thead><tr><th>Chipset</th><th>Card</th><th>USB ID</th><th>Bus/Addr</th><th>State</th></tr></thead>
    <tbody>
      {#each devices as d (`${d.vid}:${d.pid}:${d.bus}:${d.address}`)}
        <tr>
          <td><strong>{d.chipset}</strong></td>
          <td>{[d.vendor, d.product].filter(Boolean).join(' ') || '—'}</td>
          <td class="mono">{vidpid(d)}</td>
          <td class="num">{d.bus ?? '—'} / {d.address ?? '—'}</td>
          <td>{d.attached ? '● attached' : '○ present'}</td>
        </tr>
      {/each}
    </tbody>
  </table>
{/if}
