<script lang="ts">
  import { api } from '../lib/api';

  const KINDS = [
    { kind: 'csv', label: '📄 CSV Spreadsheet', hint: 'Network list and device tables in spreadsheet format — open in Excel or Google Sheets.' },
    { kind: 'netxml', label: '🗺 netXML (Kismet)', hint: 'Network and client data in Kismet-compatible format for further analysis.' },
    { kind: 'cracked', label: '🔑 Cracked Passwords', hint: 'One network name and password per line — share with your team or import into other tools.' },
    { kind: 'html', label: '📊 HTML Report', hint: 'Full visual summary with scan results, captures, cracks, and batch attack steps.' }
  ];
</script>

<h2>📤 Export Results</h2>
<p class="hint">Generated on the fly from your live scan data and captured results.</p>

<div class="cards">
  {#each KINDS as k (k.kind)}
    <section class="card">
      <h3>{k.label}</h3>
      <p>{k.hint}</p>
      <a class="btn" href={api.exportUrl(k.kind)} download>↓ Download</a>
    </section>
  {/each}
</div>

<h3>HTML preview</h3>
<iframe title="report preview" src={api.exportUrl('html')}></iframe>
