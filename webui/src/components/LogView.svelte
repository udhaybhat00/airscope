<script lang="ts">
  import { afterUpdate } from 'svelte';
  import { attackLines } from '../lib/stores';
  import { plainEnglish } from '../lib/log_translate';

  let box: HTMLDivElement;
  afterUpdate(() => {
    box?.scrollTo({ top: box.scrollHeight });
  });
</script>

<div class="log" bind:this={box}>
  {#each $attackLines.slice(-100) as line}
    <div>{plainEnglish(line)}</div>
  {:else}
    <div class="empty-inline">No attack output yet — start one above.</div>
  {/each}
</div>
