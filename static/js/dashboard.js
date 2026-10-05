/* Dashboard: one tooltip for every bar/column, on hover and keyboard focus.
   Values are also on the bars or in the table view, so the tooltip never gates information. */
(function () {
  "use strict";
  var tip = document.getElementById("viz-tooltip");
  if (!tip) return;

  function show(el) {
    tip.replaceChildren();
    var value = document.createElement("strong");
    value.textContent = el.dataset.tipValue;          // textContent: labels are data, never HTML
    var label = document.createElement("span");
    label.textContent = el.dataset.tipLabel;
    tip.append(value, label);
    if (el.dataset.tipExtra) {
      var extra = document.createElement("span");
      extra.className = "extra";
      extra.textContent = el.dataset.tipExtra;
      tip.append(extra);
    }
    tip.hidden = false;
    var r = el.getBoundingClientRect();
    var t = tip.getBoundingClientRect();
    var left = Math.min(Math.max(8, r.left + r.width / 2 - t.width / 2), window.innerWidth - t.width - 8);
    var top = r.top - t.height - 8;
    if (top < 8) top = r.bottom + 8;
    tip.style.left = left + window.scrollX + "px";
    tip.style.top = top + window.scrollY + "px";
    el.classList.add("is-hover");
  }

  function hide(el) {
    tip.hidden = true;
    if (el) el.classList.remove("is-hover");
  }

  document.querySelectorAll("[data-tip-value]").forEach(function (el) {
    el.addEventListener("pointerenter", function () { show(el); });
    el.addEventListener("pointerleave", function () { hide(el); });
    el.addEventListener("focus", function () { show(el); });
    el.addEventListener("blur", function () { hide(el); });
  });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") tip.hidden = true; });

  document.addEventListener("change", function (e) {
    if (e.target.matches("select[data-autosubmit]")) e.target.form.submit();
  });
})();
