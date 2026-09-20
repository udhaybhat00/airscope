<script lang="ts">
  import { api } from '../lib/api';
  import { aps, paletteOpen, scanning } from '../lib/stores';

  interface Item {
    id: string;
    group: string;
    label: string;
    hint: string;
    run: () => void;
  }

  let query = $state('');
  let cursor = $state(0);
  let input: HTMLInputElement;

  function go(hash: string) {
    location.hash = hash;
    paletteOpen.set(false);
  }

  function download(kind: string) {
    const a = document.createElement('a');
    a.href = api.exportUrl(kind);
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
    paletteOpen.set(false);
  }

  async function toggleScan() {
    const on = !$scanning;
    try {
      await api.setScanning(on);
    } catch {
      // The status strip already shows the failure via stalled ticks.
    }
    paletteOpen.set(false);
  }

  const items = $derived.by(() => {
    const q = query.trim().toLowerCase();
    const all: Item[] = [
      { id: 'nav-scanner', group: 'Go', label: 'Scanner', hint: 'live AP table', run: () => go('#/') },
      { id: 'nav-devices', group: 'Go', label: 'Devices', hint: 'USB adapters', run: () => go('#/devices') },
      { id: 'nav-vault', group: 'Go', label: 'Vault', hint: 'captures + crack', run: () => go('#/vault') },
      { id: 'nav-reports', group: 'Go', label: 'Reports', hint: 'csv · netxml · html', run: () => go('#/reports') },
      {
        id: 'scan-toggle', group: 'Scan', label: $scanning ? 'Stop scan' : 'Start scan',
        hint: 'channel hopping', run: toggleScan
      },
      ...[...$aps.values()]
        .filter((ap) => {
          if (!q) return true;
          // "target" doubles as the group selector, so `target home` finds HomeNet.
          const hay = `target ${ap.ssid ?? ''} ${ap.bssid}`.toLowerCase();
          return q.split(/\s+/).every((t) => hay.includes(t));
        })
        .slice(0, 8)
        .map((ap) => ({
          id: `target-${ap.bssid}`, group: 'Target',
          label: `${ap.ssid ?? '<hidden>'} · ${ap.signal} dBm`, hint: ap.bssid,
          run: () => go(`#/target/${ap.bssid}`)
        })),
      ...(['csv', 'netxml', 'cracked', 'html'] as const).map((kind) => ({
        id: `export-${kind}`, group: 'Export', label: `Download ${kind}`,
        hint: 'report file', run: () => download(kind)
      }))
    ];
    if (!q) return all;
    const tokens = q.split(/\s+/);
    return all.filter((i) => {
      const hay = `${i.group} ${i.label} ${i.hint}`.toLowerCase();
      return tokens.every((t) => hay.includes(t));
    });
  });

  function onkey(e: KeyboardEvent) {
    if (e.key === 'Escape') paletteOpen.set(false);
    else if (e.key === 'ArrowDown') {
      e.preventDefault();
      cursor = (cursor + 1) % Math.max(1, items.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      cursor = (cursor - 1 + Math.max(1, items.length)) % Math.max(1, items.length);
    } else if (e.key === 'Enter') {
      items[cursor]?.run();
    }
  }

  $effect(() => {
    query;
    cursor = 0;
  });
  $effect(() => {
    if ($paletteOpen) requestAnimationFrame(() => input?.focus());
  });
</script>

{#if $paletteOpen}
  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
  <div class="shade" onclick={() => paletteOpen.set(false)}>
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <div class="palette" role="dialog" aria-label="command palette" onclick={(e) => e.stopPropagation()} onkeydown={onkey}>
      <input bind:this={input} bind:value={query} placeholder="Type a command, SSID, or BSSID…" />
      <div class="list">
        {#each items as item, i (item.id)}
          <div class="row" class:sel={i === cursor} onclick={() => item.run()}>
            <span class="group">{item.group}</span>
            <span class="label">{item.label}</span>
            <span class="hint">{item.hint}</span>
          </div>
        {:else}
          <div class="row"><span class="hint">○ No matches.</span></div>
        {/each}
      </div>
      <div class="foot">↑↓ navigate · Enter run · Esc close</div>
    </div>
  </div>
{/if}
