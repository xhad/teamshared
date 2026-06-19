(function () {
  var toggle = document.querySelector("[data-nav-toggle]");
  var overlay = document.querySelector("[data-nav-overlay]");
  if (toggle) {
    function setOpen(open) {
      document.body.classList.toggle("nav-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }

    toggle.addEventListener("click", function () {
      setOpen(!document.body.classList.contains("nav-open"));
    });

    if (overlay) {
      overlay.addEventListener("click", function () {
        setOpen(false);
      });
    }

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") setOpen(false);
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 768) setOpen(false);
    });
  }

  document.querySelectorAll("[data-catalog-filter]").forEach(function (input) {
    var list = document.querySelector(input.getAttribute("data-catalog-list") || "");
    var cardSel = input.getAttribute("data-catalog-card") || ".catalog-card";
    var empty = document.querySelector(input.getAttribute("data-catalog-empty") || "");
    var count = document.querySelector(input.getAttribute("data-catalog-count") || "");
    if (!list) return;
    var cards = Array.prototype.slice.call(list.querySelectorAll(cardSel));

    function apply() {
      var q = input.value.trim().toLowerCase();
      var shown = 0;
      cards.forEach(function (card) {
        var hit = !q || (card.getAttribute("data-search") || "").indexOf(q) !== -1;
        card.style.display = hit ? "" : "none";
        if (hit) shown++;
      });
      if (empty) empty.style.display = shown === 0 ? "" : "none";
      if (count) count.textContent = q ? shown + " / " + cards.length : "";
    }

    input.addEventListener("input", apply);
  });

  document.querySelectorAll("[data-playbook-skill-picker]").forEach(function (root) {
    var list = root.querySelector("[data-selected-list]");
    var empty = root.querySelector("[data-selected-empty]");
    var error = root.querySelector("[data-picker-error]");
    var textarea = root.querySelector("#pb-skills");
    var form = document.getElementById("pb-form");
    if (!list || !textarea) return;

    var selected = [];
    try {
      selected = JSON.parse(root.getAttribute("data-initial") || "[]");
      if (!Array.isArray(selected)) selected = [];
    } catch (e) {
      selected = [];
    }

    function syncTextarea() {
      textarea.value = selected.join("\n");
    }

    function cardFor(name) {
      return root.querySelector('.skill-picker-card[data-skill-name="' + name + '"]');
    }

    function updateAddButtons() {
      root.querySelectorAll("[data-skill-add]").forEach(function (btn) {
        var card = btn.closest(".skill-picker-card");
        var name = card && card.getAttribute("data-skill-name");
        var on = name && selected.indexOf(name) !== -1;
        btn.disabled = !!on;
        btn.textContent = on ? "Added" : "Add";
        if (card) card.classList.toggle("is-added", !!on);
      });
    }

    function renderSelected() {
      list.innerHTML = "";
      selected.forEach(function (name, idx) {
        var li = document.createElement("li");
        li.className = "skill-picker-selected-item";
        li.setAttribute("data-skill-name", name);

        var label = document.createElement("span");
        label.className = "skill-picker-selected-name";
        label.textContent = name;
        li.appendChild(label);

        var actions = document.createElement("span");
        actions.className = "skill-picker-selected-actions";

        function mkBtn(text, title, handler) {
          var b = document.createElement("button");
          b.type = "button";
          b.className = "ghost skill-picker-icon-btn";
          b.textContent = text;
          b.title = title;
          b.setAttribute("aria-label", title);
          b.addEventListener("click", handler);
          return b;
        }

        if (idx > 0) {
          actions.appendChild(mkBtn("\u2191", "Move up", function () {
            var tmp = selected[idx - 1];
            selected[idx - 1] = selected[idx];
            selected[idx] = tmp;
            renderSelected();
          }));
        }
        if (idx < selected.length - 1) {
          actions.appendChild(mkBtn("\u2193", "Move down", function () {
            var tmp = selected[idx + 1];
            selected[idx + 1] = selected[idx];
            selected[idx] = tmp;
            renderSelected();
          }));
        }
        actions.appendChild(mkBtn("\u00d7", "Remove " + name, function () {
          selected = selected.filter(function (n) { return n !== name; });
          renderSelected();
        }));
        li.appendChild(actions);
        list.appendChild(li);
      });

      if (empty) empty.hidden = selected.length > 0;
      if (error) error.hidden = true;
      syncTextarea();
      updateAddButtons();
    }

    root.querySelectorAll("[data-skill-add]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var card = btn.closest(".skill-picker-card");
        var name = card && card.getAttribute("data-skill-name");
        if (!name || selected.indexOf(name) !== -1) return;
        selected.push(name);
        renderSelected();
      });
    });

    if (form) {
      form.addEventListener("submit", function (e) {
        syncTextarea();
        if (!textarea.value.trim()) {
          e.preventDefault();
          if (error) error.hidden = false;
          if (empty) empty.hidden = false;
        }
      });
    }

    renderSelected();
  });
})();
