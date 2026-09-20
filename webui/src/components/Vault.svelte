<script lang="ts">
  import { onMount } from 'svelte';
  import { api, type Capture } from '../lib/api';
  import { cracks, vaultVersion } from '../lib/stores';

  interface VaultAp {
    bssid: string;
    ssid: string | null;
    captures: Capture[];
  }

  let groups: VaultAp[] = $state([]);
  let error: string | null = $state(null);
  let wordlists: Record<string, string> = $state({});
  let starting: string | null = $state(null);

  async function load() {
    try {
      const d = await api.vault();
      groups = d.aps;
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  onMount(() => {
    load();
    const off = vaultVersion.subscribe(() => load());
    return off;
  });

  function crackable(c: Capture): boolean {
    return (c.type === 'HS' || c.type === 'PMKID') && c.record_count > 0;
  }

  function captureLabel(type: string): string {
    if (type === 'HS') return '4-Way Handshake';
    if (type === 'PMKID') return 'PMKID Capture';
    if (type === 'PSK') return 'Recovered PSK';
    return type;
  }

  async function remove(path: string) {
    try {
      await api.deleteCapture(path);
      await load();
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    }
  }

  async function crack(path: string) {
    const wordlist = (wordlists[path] ?? '').trim();
    if (!wordlist) {
      error = 'Enter a wordlist path first.';
      return;
    }
    starting = path;
    error = null;
    try {
      await api.startCrack(path, wordlist);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      starting = null;
    }
  }

  function progress(path: string): string {
    for (const [, entry] of $cracks) {
      if (entry.job.path === path && entry.job.state === 'running') {
        const pct = entry.total ? Math.round((100 * entry.tested) / entry.total) : 0;
        return `Cracking… ${entry.tested.toLocaleString()} / ${entry.total.toLocaleString()} passwords (${pct}%) ${entry.speed}`;
      }
      if (entry.job.path === path && entry.psk) return `✓ Password recovered: ${entry.psk}`;
      if (entry.job.path === path) return entry.job.state;
    }
    return '';
  }
</script>

<h2>📋 Captured Results</h2>
<p class="hint">Handshakes, PMKIDs, and recovered passwords from your scans.</p>

{#if error}
  <div class="error">{error}</div>
{/if}

{#if groups.length === 0}
  <div class="empty">
    No captured handshakes yet — go to the <a href="#/">Scanner</a> tab, pick a network, and capture.
  </div>
{:else}
  {#each groups as g (g.bssid)}
    <section class="vault-ap">
      <h3>{g.ssid ?? '<hidden>'} <small class="mono">{g.bssid}</small></h3>
      <table class="scan">
        <thead><tr><th>Type</th><th>Records</th><th>Value</th><th>Actions</th></tr></thead>
        <tbody>
          {#each g.captures as c (c.path)}
            <tr>
              <td>{captureLabel(c.type)}</td>
              <td class="num">{c.record_count}</td>
              <td>{c.has_value ? '✓ saved' : ''}</td>
              <td class="actions">
                <a class="btn" href={api.downloadUrl(c.path)} download>↓ Download</a>
                <button class="btn danger" onclick={() => remove(c.path)}>✕ Remove</button>
                {#if crackable(c)}
                  <input
                    placeholder="/usr/share/wordlists/rockyou.txt"
                    value={wordlists[c.path] ?? ''}
                    oninput={(e) => (wordlists[c.path] = e.currentTarget.value)}
                  />
                  <button class="btn" disabled={starting === c.path} onclick={() => crack(c.path)}>
                    {starting === c.path ? 'Starting…' : '🔍 Crack'}
                  </button>
                  {#if progress(c.path)}
                    <span class="crack-progress">{progress(c.path)}</span>
                  {/if}
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </section>
  {/each}
{/if}
