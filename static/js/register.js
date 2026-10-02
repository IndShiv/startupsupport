/* Registration form enhancements. Without JavaScript the form still works:
   all sections are shown on one page and the server validates everything. */
(function () {
  "use strict";

  var form = document.getElementById("registration-form");
  if (!form) return;

  var employeeDomains = (form.dataset.employeeDomains || "").split(" ").filter(Boolean);
  var graduationYears = (form.dataset.graduationYears || "").split(" ").filter(Boolean);
  var sections = Array.prototype.slice.call(form.querySelectorAll("[data-section]"));
  var progressItems = Array.prototype.slice.call(form.querySelectorAll("[data-progress]"));
  var status = document.getElementById("step-status");
  var current = 0;
  var msgEl = document.getElementById("register-messages");
  var T = msgEl ? JSON.parse(msgEl.textContent) : {};
  function t(key, vars) {
    var text = T[key] || key;
    Object.keys(vars || {}).forEach(function (k) { text = text.replace("%(" + k + ")s", vars[k]); });
    return text;
  }

  function $(selector) { return form.querySelector(selector); }
  function all(selector) { return Array.prototype.slice.call(form.querySelectorAll(selector)); }
  function checkedValue(name) {
    var el = form.querySelector('input[name="' + name + '"]:checked');
    return el ? el.value : "";
  }

  // ---- conditional logic ------------------------------------------------
  function onGraduationTrack() { return graduationYears.indexOf(checkedValue("study_year")) !== -1; }

  function updateConditional() {
    var grad = onGraduationTrack();
    form.querySelector('[data-section="graduation"]').dataset.skip = grad ? "" : "1";
    form.querySelector('[data-progress="graduation"]').hidden = !grad;
    // Graduation fields are required only on the graduation track.
    all('[data-section="graduation"] input, [data-section="graduation"] textarea').forEach(function (el) {
      el.required = grad;
    });

    // Student number is optional for employees.
    var isEmployee = employeeDomains.indexOf(checkedValue("domain")) !== -1;
    var number = $("#id_student_number");
    number.required = !isEmployee;
    var field = $("#field-student_number");
    field.querySelector(".optional-note").hidden = !isEmployee;
    field.querySelector(".req").hidden = isEmployee;

    // Approval notice.
    $("#approval-notice").hidden = !(grad && checkedValue("grad_approval") === "not_yet");

    // De-emphasise coaches from the student's own domain on the graduation track.
    var domain = checkedValue("domain");
    var anySame = false;
    all(".coach-card[data-domains]").forEach(function (card) {
      var same = grad && domain && card.dataset.domains.split(" ").indexOf(domain) !== -1;
      card.classList.toggle("same-domain", same);
      card.querySelector(".same-domain-badge").hidden = !same;
      anySame = anySame || same;
    });
    $("#same-domain-hint").hidden = !anySame;
    renderProgress();
  }

  // ---- word counters ----------------------------------------------------
  function countWords(text) { return text.trim() ? text.trim().split(/\s+/).length : 0; }

  all("textarea[data-max-words]").forEach(function (textarea) {
    var limit = parseInt(textarea.dataset.maxWords, 10);
    var counter = document.getElementById(textarea.id + "_counter");
    var wasOver = false;
    function update() {
      var words = countWords(textarea.value);
      var over = words > limit;
      counter.textContent = t(over ? "words_over" : "words", { words: words, limit: limit });
      counter.classList.toggle("over", over);
      textarea.setCustomValidity(over ? t("max_words", { limit: limit }) : "");
      // Only announce when crossing the limit, not on every keystroke.
      if (over !== wasOver) {
        counter.setAttribute("aria-live", "polite");
        wasOver = over;
      }
    }
    textarea.addEventListener("input", update);
    update();
  });

  // ---- hints ------------------------------------------------------------
  var email = $("#id_email");
  var emailHint = document.getElementById("email-hint");
  function updateEmailHint() {
    var v = email.value.trim().toLowerCase();
    emailHint.hidden = !(v.indexOf("@") > 0 && !/@buas\.nl$/.test(v));
  }
  // Update while typing (not on blur): a hint appearing on blur shifts the layout under the pointer.
  email.addEventListener("input", updateEmailHint);
  updateEmailHint();

  var handIn = $("#id_grad_hand_in_date");
  var handInHint = document.getElementById("hand-in-hint");
  var tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  handIn.min = tomorrow.toISOString().slice(0, 10);
  function updateHandInHint() {
    if (!handIn.value) { handInHint.hidden = true; return; }
    var days = (new Date(handIn.value) - new Date()) / 86400000;
    handInHint.hidden = !(days > 0 && days < 28);
  }
  handIn.addEventListener("change", updateHandInHint);
  updateHandInHint();

  // ---- steps ------------------------------------------------------------
  function visibleSections() { return sections.filter(function (s) { return s.dataset.skip !== "1"; }); }

  function renderProgress() {
    var visible = visibleSections();
    var active = sections[current];
    var activeIndex = visible.indexOf(active);
    progressItems.forEach(function (li) {
      var section = form.querySelector('[data-section="' + li.dataset.progress + '"]');
      var idx = visible.indexOf(section);
      li.classList.toggle("current", section === active);
      li.classList.toggle("done", idx !== -1 && idx < activeIndex);
      if (section === active) li.setAttribute("aria-current", "step"); else li.removeAttribute("aria-current");
    });
    visible.forEach(function (s, i) {
      s.querySelector("[data-prev]").hidden = i === 0;
      s.querySelector("[data-next]").hidden = i === visible.length - 1;
    });
  }

  function show(index, focus) {
    sections.forEach(function (s, i) { s.classList.toggle("active", i === index); });
    current = index;
    renderProgress();
    var visible = visibleSections();
    var section = sections[index];
    if (status) {
      status.textContent = t("step", { n: visible.indexOf(section) + 1, total: visible.length, title: section.querySelector("h2").textContent });
    }
    if (focus) {
      section.querySelector("h2").focus();
      section.scrollIntoView({ block: "start" });
    }
  }

  function step(direction) {
    var visible = visibleSections();
    var idx = visible.indexOf(sections[current]) + direction;
    if (idx >= 0 && idx < visible.length) show(sections.indexOf(visible[idx]), true);
  }

  function validateSection(section) {
    var invalid = null;
    all('[data-section="' + section.dataset.section + '"] input, [data-section="' + section.dataset.section + '"] textarea').forEach(function (el) {
      if (el.name === "website" || el.type === "hidden") return;
      var field = el.closest(".field");
      if (!field) return;
      var ok = el.checkValidity();
      if (!ok && !invalid) invalid = el;
    });
    // Mark/unmark whole fields so radios in a group are handled together.
    all('[data-section="' + section.dataset.section + '"] .field').forEach(function (field) {
      var inputs = Array.prototype.slice.call(field.querySelectorAll("input, textarea"));
      var bad = inputs.some(function (el) { return !el.checkValidity(); });
      var msg = field.querySelector(".client-error");
      if (bad) {
        if (!msg) {
          msg = document.createElement("p");
          msg.className = "error client-error";
          msg.id = field.id + "-client-error";
          // Same place as server-side errors: after the label and help text, before the input.
          var help = field.querySelector(".help");
          var anchor = help || field.querySelector("label, legend");
          anchor.parentNode.insertBefore(msg, anchor.nextSibling);
          inputs.forEach(function (el) {
            var d = el.getAttribute("aria-describedby") || "";
            if (d.indexOf(msg.id) === -1) el.setAttribute("aria-describedby", (d + " " + msg.id).trim());
          });
        }
        var first = inputs.filter(function (el) { return !el.checkValidity(); })[0];
        msg.textContent = messageFor(first);
        field.classList.add("has-error");
      } else if (msg) {
        msg.remove();
        field.classList.remove("has-error");
      }
    });
    if (invalid) {
      invalid.focus();
      return false;
    }
    return true;
  }

  function messageFor(el) {
    var v = el.validity;
    if (el.type === "radio") return t("choose");
    if (el.type === "checkbox") return t("tick");
    if (v.valueMissing) return t("required");
    if (v.typeMismatch && el.type === "email") return t("email");
    if (v.patternMismatch && el.name === "student_number") return t("student_number");
    if (v.rangeUnderflow) return t("future_date");
    return el.validationMessage;
  }

  form.addEventListener("click", function (e) {
    if (e.target.matches("[data-next]")) {
      if (validateSection(sections[current])) step(1);
    } else if (e.target.matches("[data-prev]")) {
      step(-1);
    }
  });

  // Clear a field's error as soon as it becomes valid. This runs on "input" (while typing),
  // not only on "change", so messages don't disappear on blur and shift the layout under the pointer.
  function clearFixedError(e) {
    var field = e.target.closest(".field.has-error");
    if (field && Array.prototype.every.call(field.querySelectorAll("input, textarea"), function (el) { return el.checkValidity(); })) {
      var msg = field.querySelector(".client-error");
      if (msg) msg.remove();
      field.classList.remove("has-error");
    }
  }
  form.addEventListener("input", clearFixedError);
  form.addEventListener("change", function (e) {
    if (["domain", "study_year", "grad_approval"].indexOf(e.target.name) !== -1) updateConditional();
    clearFixedError(e);
  });

  form.addEventListener("submit", function (e) {
    var visible = visibleSections();
    for (var i = 0; i < visible.length; i++) {
      if (!validateSection(visible[i])) {
        e.preventDefault();
        show(sections.indexOf(visible[i]), false);
        validateSection(visible[i]);
        return;
      }
    }
    var btn = form.querySelector("[data-submit]");
    btn.disabled = true;
    btn.textContent = t("sending");
  });

  // Error summary links jump to the right step.
  document.addEventListener("click", function (e) {
    var link = e.target.closest("[data-goto]");
    if (!link) return;
    e.preventDefault();
    var field = document.getElementById("field-" + link.dataset.goto);
    var section = field.closest("[data-section]");
    show(sections.indexOf(section), false);
    var input = field.querySelector("input, textarea");
    if (input) input.focus();
  });

  // ---- start ------------------------------------------------------------
  updateConditional();
  var firstWithErrors = sections.filter(function (s) { return s.hasAttribute("data-has-errors") && s.dataset.skip !== "1"; })[0];
  show(firstWithErrors ? sections.indexOf(firstWithErrors) : 0, false);
  var summary = document.getElementById("error-summary");
  if (summary) summary.focus();
})();
