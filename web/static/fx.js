/* Ambient aurora background: a handful of soft gradient blobs drifting very
 * slowly behind the UI. Drawn at 1/6 resolution and upscaled (the blobs are
 * blurry by nature, so the upscale is invisible) — the per-frame cost is a
 * few hundred pixels of radial gradients, cheap enough for a phone. Runs at
 * ~30fps, pauses when the tab is hidden, and renders a single static frame
 * when the user prefers reduced motion.
 */
(function () {
  var canvas = document.getElementById("bg-fx");
  if (!canvas) return;

  var ctx = canvas.getContext("2d");
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var SCALE = 6; // internal resolution divisor
  var w, h;

  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  // Blob colors follow the theme's accent tokens so light/dark both work.
  var colors = [
    cssVar("--fx-1", "#7C5CFF"),
    cssVar("--fx-2", "#2BE0C8"),
    cssVar("--fx-3", "#3E7BFF"),
    cssVar("--fx-4", "#E0699B"),
  ];
  var alpha = parseFloat(cssVar("--fx-alpha", "0.16")) || 0.16;

  var blobs = [
    { c: colors[0], r: 0.52, x: 0.18, y: 0.12, dx: 0.00013, dy: 0.00011, p: 0.0 },
    { c: colors[1], r: 0.44, x: 0.85, y: 0.25, dx: 0.00011, dy: 0.00014, p: 2.1 },
    { c: colors[2], r: 0.48, x: 0.55, y: 0.85, dx: 0.00012, dy: 0.0001, p: 4.2 },
    { c: colors[3], r: 0.34, x: 0.1, y: 0.75, dx: 0.0001, dy: 0.00012, p: 1.3 },
  ];

  function resize() {
    w = Math.max(1, Math.round(window.innerWidth / SCALE));
    h = Math.max(1, Math.round(window.innerHeight / SCALE));
    canvas.width = w;
    canvas.height = h;
  }

  function draw(t) {
    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = "lighter";
    for (var i = 0; i < blobs.length; i++) {
      var b = blobs[i];
      var cx = (b.x + Math.sin(t * b.dx + b.p) * 0.1) * w;
      var cy = (b.y + Math.cos(t * b.dy + b.p) * 0.12) * h;
      var r = b.r * Math.max(w, h);
      var g = ctx.createRadialGradient(cx, cy, 0, cx, cy, r);
      g.addColorStop(0, b.c);
      g.addColorStop(1, "transparent");
      ctx.globalAlpha = alpha;
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }

  var rafId = null;
  var lastFrame = 0;
  function loop(now) {
    rafId = requestAnimationFrame(loop);
    if (now - lastFrame < 33) return; // ~30fps is plenty for slow drift
    lastFrame = now;
    draw(now);
  }

  function start() {
    if (rafId === null) rafId = requestAnimationFrame(loop);
  }
  function stop() {
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  resize();
  window.addEventListener("resize", function () {
    resize();
    if (reduceMotion) draw(0);
  });

  if (reduceMotion) {
    draw(0); // one static frame, no animation
    return;
  }

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) stop();
    else start();
  });
  start();
})();
