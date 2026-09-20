<script lang="ts">
  import type { ApSnap } from '../lib/api';
  import { encClass, encIcon } from '../lib/format';
  import { marked } from '../lib/stores';

  interface Props {
    aps: ApSnap[];
    now: number;
  }
  let { aps, now }: Props = $props();

  const STALE_S = 10;
  const sorted = $derived(
    [...aps].sort((a, b) => (b.signal ?? -100) - (a.signal ?? -100))
  );
  function stale(ap: ApSnap): boolean {
    return !ap.last_seen || now / 1000 - ap.last_seen > STALE_S;
  }
  /** 0–4 filled bars from dBm (pure CSS: no exotic glyphs needed). */
  function bars(dbm: number | null | undefined): number {
    if (dbm === null || dbm === undefined) return 0;
    if (dbm < -80) return 1;
    if (dbm < -70) return 2;
    if (dbm < -60) return 3;
    return 4;
  }
</script>

<table class="scan">
  <thead>
    <tr>
      <th></th>
      <th class="num">SIG</th>
      <th>SSID</th>
      <th class="num">CH</th>
      <th>ENC</th>
      <th class="num">CLIENTS</th>
      <th class="num">BEACONS</th>
    </tr>
  </thead>
  <tbody>
    {#each sorted as ap (ap.bssid)}
      <tr class:stale={stale(ap)} onclick={() => (location.hash = `#/target/${ap.bssid}`)}>
        <td onclick={(e) => e.stopPropagation()} class="check">
          <input
            type="checkbox"
            checked={$marked.has(ap.bssid)}
            onchange={() => {
              $marked.has(ap.bssid) ? $marked.delete(ap.bssid) : $marked.add(ap.bssid);
              $marked = new Set($marked);
            }}
            aria-label={`mark ${ap.ssid ?? ap.bssid} for batch`}
          />
        </td>
        <td class="num sig">
          <span class="bars" aria-hidden="true">
            {#each [1, 2, 3, 4] as i}
              <span class:on={i <= bars(ap.signal)}></span>
            {/each}
          </span>
          {ap.signal} dBm
        </td>
        <td>{ap.ssid ?? '<hidden>'}</td>
        <td class="num">{ap.channel}</td>
        <td><span class="enc {encClass(ap.encryption)}">{encIcon(ap.encryption)} {ap.encryption}</span></td>
        <td class="num">{ap.clients.length || ''}</td>
        <td class="num">{ap.beacons}</td>
      </tr>
    {/each}
  </tbody>
</table>

{#if sorted.length === 0}
  <div class="empty">○ No access points in range — waiting for the scan…</div>
{/if}
