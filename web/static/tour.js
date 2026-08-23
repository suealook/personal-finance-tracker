/* Reusable spotlight-tour engine: one element highlighted at a time, a
 * tooltip with Back/Next/Skip. Deliberately generic (steps come from the
 * caller) so any page can define its own sequence without touching this
 * file — see dashboard.html for the step definitions.
 */
window.Tour = (function () {
  function start(steps, opts) {
    opts = opts || {};
    var idx = 0;
    var overlay, tooltip;

    function build() {
      overlay = document.createElement("div");
      overlay.className = "tour-overlay";
      document.body.appendChild(overlay);

      tooltip = document.createElement("div");
      tooltip.className = "tour-tooltip";
      tooltip.setAttribute("role", "dialog");
      tooltip.setAttribute("aria-live", "polite");
      document.body.appendChild(tooltip);
    }

    function teardown(finished) {
      if (overlay) overlay.remove();
      if (tooltip) tooltip.remove();
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("resize", reposition);
      if (opts.onEnd) opts.onEnd(finished);
    }

    function reposition() {
      var step = steps[idx];
      var target = step.selector ? document.querySelector(step.selector) : null;
      var rect = target ? target.getBoundingClientRect() : null;

      if (rect && rect.width > 0) {
        var pad = 8;
        overlay.classList.remove("tour-overlay--full");
        overlay.style.top = (rect.top - pad) + "px";
        overlay.style.left = (rect.left - pad) + "px";
        overlay.style.width = (rect.width + pad * 2) + "px";
        overlay.style.height = (rect.height + pad * 2) + "px";
      } else {
        overlay.classList.add("tour-overlay--full");
      }

      var tRect = tooltip.getBoundingClientRect();
      var top, left;
      if (rect && rect.width > 0) {
        var spaceBelow = window.innerHeight - rect.bottom;
        top = spaceBelow > tRect.height + 24 ? rect.bottom + 14 : rect.top - tRect.height - 14;
        left = rect.left;
      } else {
        top = (window.innerHeight - tRect.height) / 2;
        left = (window.innerWidth - tRect.width) / 2;
      }
      left = Math.min(Math.max(left, 16), window.innerWidth - tRect.width - 16);
      top = Math.min(Math.max(top, 16), window.innerHeight - tRect.height - 16);
      tooltip.style.top = top + "px";
      tooltip.style.left = left + "px";
    }

    function render() {
      var step = steps[idx];
      var target = step.selector ? document.querySelector(step.selector) : null;
      if (target) target.scrollIntoView({ block: "center", behavior: "smooth" });

      var dots = steps
        .map(function (_, i) {
          var cls = i === idx ? "active" : i < idx ? "done" : "";
          return '<span class="tour-dot ' + cls + '"></span>';
        })
        .join("");

      tooltip.innerHTML =
        '<div class="tour-progress">' + dots + "</div>" +
        '<h3 class="tour-title"></h3>' +
        '<p class="tour-text"></p>' +
        '<div class="tour-actions">' +
        '<button type="button" class="tour-skip">Skip tour</button>' +
        '<div class="tour-nav">' +
        (idx > 0 ? '<button type="button" class="tour-back btn-ghost">Back</button>' : "") +
        '<button type="button" class="tour-next"></button>' +
        "</div>" +
        "</div>";

      // textContent, not innerHTML, for step copy -- steps can come from
      // server-templated strings and must never be interpreted as markup.
      tooltip.querySelector(".tour-title").textContent = step.title;
      tooltip.querySelector(".tour-text").textContent = step.text;
      tooltip.querySelector(".tour-next").textContent =
        idx === steps.length - 1 ? step.finishLabel || "Done" : "Next";

      tooltip.querySelector(".tour-skip").addEventListener("click", function () {
        teardown(false);
      });
      tooltip.querySelector(".tour-next").addEventListener("click", next);
      var backBtn = tooltip.querySelector(".tour-back");
      if (backBtn) backBtn.addEventListener("click", back);

      // Reposition after the scroll-into-view above has had time to settle
      // (Doherty Threshold: quick enough to feel responsive, not instant
      // enough to reposition against a still-scrolling page).
      setTimeout(reposition, target ? 260 : 0);
    }

    function next() {
      idx++;
      if (idx >= steps.length) {
        teardown(true);
        return;
      }
      render();
    }
    function back() {
      idx = Math.max(0, idx - 1);
      render();
    }
    function onKey(e) {
      if (e.key === "Escape") teardown(false);
      else if (e.key === "ArrowRight") next();
      else if (e.key === "ArrowLeft") back();
    }

    build();
    document.addEventListener("keydown", onKey);
    window.addEventListener("resize", reposition);
    render();
  }

  return { start: start };
})();
