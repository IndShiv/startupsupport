/* Pipeline board: drag cards between columns, or use the "Move to…" menu / list selects.
   Everything also works without JavaScript through the plain forms. */
(function () {
  "use strict";

  var status = document.getElementById("pipeline-status");
  var msgEl = document.getElementById("pipeline-messages");
  var T = msgEl ? JSON.parse(msgEl.textContent) : {};
  var csrf = (document.querySelector("[name=csrfmiddlewaretoken]") || {}).value;

  function t(key, vars) {
    var text = T[key] || key;
    Object.keys(vars || {}).forEach(function (k) { text = text.replace("%(" + k + ")s", vars[k]); });
    return text;
  }

  function say(message, intakeUrl, isError) {
    if (!status) return;
    status.textContent = message + " ";
    status.classList.toggle("error", !!isError);
    if (intakeUrl) {
      var a = document.createElement("a");
      a.href = intakeUrl;
      a.textContent = t("open_intake");
      status.appendChild(a);
    }
  }

  function move(url, stageId) {
    var body = new FormData();
    body.append("stage", stageId);
    return fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrf, "Accept": "application/json" },
      body: body,
      credentials: "same-origin",
    }).then(function (response) {
      return response.json().then(function (data) {
        if (!response.ok || !data.ok) throw new Error(data.message || "error");
        return data;
      });
    });
  }

  function updateCounts() {
    document.querySelectorAll(".column").forEach(function (col) {
      var count = col.querySelector("[data-count]");
      var cards = col.querySelectorAll(".pcard").length;
      if (count && col.querySelector("[data-dropzone]")) count.textContent = cards;
      var empty = col.querySelector(".empty-col");
      if (empty) empty.hidden = cards > 0;
    });
  }

  function cardTitle(card) { return card.querySelector("h3").textContent.trim(); }

  function placeCard(card, column) {
    var zone = column.querySelector("[data-dropzone]");
    if (zone) {
      zone.insertBefore(card, zone.firstChild);
    } else {
      card.remove(); // moved into a collapsed (closed) column
    }
    var select = card.querySelector("select[name=stage]");
    if (select) select.value = column.dataset.stage;
    updateCounts();
  }

  // ---- drag and drop ---------------------------------------------------------------
  var board = document.getElementById("board");
  if (board) {
    var template = board.dataset.moveUrlTemplate;
    var dragged = null;

    board.addEventListener("dragstart", function (e) {
      var card = e.target.closest(".pcard");
      if (!card) return;
      dragged = card;
      card.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", card.dataset.id);
    });
    board.addEventListener("dragend", function () {
      if (dragged) dragged.classList.remove("dragging");
      dragged = null;
      board.querySelectorAll(".drop-target").forEach(function (c) { c.classList.remove("drop-target"); });
    });
    board.addEventListener("dragover", function (e) {
      var column = e.target.closest(".column");
      if (!column || !dragged) return;
      e.preventDefault();
      board.querySelectorAll(".drop-target").forEach(function (c) { if (c !== column) c.classList.remove("drop-target"); });
      column.classList.add("drop-target");
    });
    board.addEventListener("drop", function (e) {
      var column = e.target.closest(".column");
      if (!column || !dragged) return;
      e.preventDefault();
      column.classList.remove("drop-target");
      var card = dragged;
      var from = card.closest(".column");
      if (from === column) return;
      var name = cardTitle(card);
      say(t("moving", { startup: name, stage: column.dataset.stageName }));
      placeCard(card, column);
      move(template.replace("/0/", "/" + card.dataset.id + "/"), column.dataset.stage)
        .then(function (data) { say(data.message, data.intake_url); })
        .catch(function () {
          placeCard(card, from);
          say(t("failed", { startup: name }), null, true);
        });
    });
  }

  // ---- "Move to…" menus and list selects ------------------------------------------
  document.addEventListener("submit", function (e) {
    var form = e.target.closest("[data-move-form]");
    if (!form) return;
    e.preventDefault();
    var stageId = form.querySelector("select[name=stage]").value;
    var card = form.closest(".pcard");
    var name = card ? cardTitle(card) : (form.closest("tr").querySelector("a.strong") || {}).textContent;
    move(form.action, stageId).then(function (data) {
      say(data.message, data.intake_url);
      if (card) {
        var column = document.querySelector('.column[data-stage="' + stageId + '"]');
        form.closest("details").open = false;
        if (column) placeCard(card, column);
        card.querySelector("h3 a").focus();
      }
    }).catch(function () { say(t("failed", { startup: name }), null, true); });
  });

  document.addEventListener("change", function (e) {
    if (e.target.matches("select[data-autosubmit]")) {
      e.target.form.requestSubmit();
    }
  });
})();
