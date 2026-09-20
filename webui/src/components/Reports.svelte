<script lang="ts">
  import { api } from '../lib/api';

  const KINDS = [
    { kind: 'csv', label: 'CSV', hint: 'airodump-style AP + station tables' },
    { kind: 'netxml', label: 'netXML', hint: 'Kismet-compatible network + client tree' },
    { kind: 'cracked', label: 'cracked.txt', hint: 'one AP + PSK per recovered credential' },
    { kind: 'html', label: 'HTML report', hint: 'scan summary, captures, cracks, batch steps' }
  ];
</script>

<h2>Reports</h2>
<p>Generated on the fly from the live array plus VAULT.</p>

<div class="cards">
  {#each KINDS as k (k.kind)}
    <section class="card">
      <h3>{k.label}</h3>
      <p>{k.hint}</p>
      <a class="btn" href={api.exportUrl(k.kind)} download>Download</a>
    </section>
  {/each}
</div>

<h3>HTML preview</h3>
<iframe title="report preview" src={api.exportUrl('html')}></iframe>
