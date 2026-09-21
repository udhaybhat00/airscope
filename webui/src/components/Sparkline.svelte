<script lang="ts">
  /** Smooth multi-series line graph on canvas. Colors resolve from the
   * Signal Noir CSS tokens at draw time, so palette edits just work. */
  interface Props {
    series: number[][];
    tokens: string[];
    height?: number;
  }
  let { series, tokens, height = 72 }: Props = $props();

  let canvas: HTMLCanvasElement;

  function color(token: string, fallback: string): string {
    const v = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
    return v || fallback;
  }

  function draw() {
    if (!canvas) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = height;
    if (w <= 0) return;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, w, h);
    const n = Math.max(...series.map((s) => s.length), 2);
    const max = Math.max(1, ...series.flat());
    const x = (i: number) => (i / (n - 1)) * w;
    const y = (v: number) => h - 4 - (v / max) * (h - 10);
    series.forEach((pts, si) => {
      if (pts.length === 0) return;
      const stroke = color(tokens[si % tokens.length], '#60a5fa');
      const padded = pts.length === 1 ? [pts[0], pts[0]] : pts;
      ctx.beginPath();
      ctx.moveTo(x(0), y(padded[0]));
      for (let i = 1; i < padded.length; i++) {
        const xm = (x(i - 1) + x(i)) / 2;
        ctx.quadraticCurveTo(x(i - 1), y(padded[i - 1]), xm, (y(padded[i - 1]) + y(padded[i])) / 2);
      }
      ctx.lineTo(x(padded.length - 1), y(padded[padded.length - 1]));
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.lineTo(x(padded.length - 1), h);
      ctx.lineTo(x(0), h);
      ctx.closePath();
      ctx.globalAlpha = 0.15;
      ctx.fillStyle = stroke;
      ctx.fill();
      ctx.globalAlpha = 1;
    });
  }

  $effect(() => {
    series;
    draw();
  });
</script>

<canvas bind:this={canvas} style="width:100%;height:{height}px"></canvas>
