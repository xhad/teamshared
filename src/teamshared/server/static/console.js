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
})();
