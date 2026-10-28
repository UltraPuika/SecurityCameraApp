// Asks for the self-hosted dashboard address once, then opens it inside the app's WebView.
(function () {
  "use strict";
  var KEY = "camdash.server";
  var TEXT = {
    en: {
      title: "Camera dashboard",
      connecting: "Connecting to",
      change: "Change server",
      label: "Dashboard address",
      hint: "The address you open the dashboard with in a browser (for example your Tailscale HTTPS address).",
      connect: "Connect",
      invalid: "Enter a full address starting with https:// or http://",
      unreachable: "The server cannot be reached. Check the address and your VPN/Wi-Fi connection.",
      checking: "Checking…",
    },
    lv: {
      title: "Kameru panelis",
      connecting: "Savienojas ar",
      change: "Mainīt serveri",
      label: "Paneļa adrese",
      hint: "Adrese, ar kuru atverat paneli pārlūkā (piemēram, jūsu Tailscale HTTPS adrese).",
      connect: "Savienoties",
      invalid: "Ievadiet pilnu adresi, kas sākas ar https:// vai http://",
      unreachable: "Serveris nav sasniedzams. Pārbaudiet adresi un VPN/Wi-Fi savienojumu.",
      checking: "Pārbauda…",
    },
  };
  var lang = (navigator.languages || [navigator.language || ""]).some(function (l) {
    return String(l).toLowerCase().indexOf("lv") === 0;
  })
    ? "lv"
    : "en";
  var t = TEXT[lang];
  document.documentElement.lang = lang;
  document.querySelectorAll("[data-i18n]").forEach(function (el) {
    el.textContent = t[el.getAttribute("data-i18n")];
  });

  var form = document.getElementById("form");
  var input = document.getElementById("url");
  var error = document.getElementById("error");
  var auto = document.getElementById("auto");
  var timer;

  function normalise(value) {
    var v = String(value || "").trim();
    if (!/^https?:\/\//i.test(v)) return null;
    try {
      var u = new URL(v);
      if (u.username || u.password) return null;
      return u.origin;
    } catch (e) {
      return null;
    }
  }

  function open(url) {
    // Keep the launcher in history so Android "back" returns here to change servers.
    window.location.href = url + "/";
  }

  function showForm(prefill) {
    clearTimeout(timer);
    auto.hidden = true;
    form.hidden = false;
    input.value = prefill || "";
    input.focus();
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    error.hidden = true;
    var url = normalise(input.value);
    if (!url) {
      error.textContent = t.invalid;
      error.hidden = false;
      return;
    }
    var button = form.querySelector("button");
    button.disabled = true;
    button.textContent = t.checking;
    // Opaque request: only tells us whether the server answers at all.
    fetch(url + "/api/health", { mode: "no-cors", cache: "no-store" })
      .then(function () {
        localStorage.setItem(KEY, url);
        open(url);
      })
      .catch(function () {
        error.textContent = t.unreachable;
        error.hidden = false;
      })
      .finally(function () {
        button.disabled = false;
        button.textContent = t.connect;
      });
  });

  document.getElementById("change").addEventListener("click", function () {
    showForm(localStorage.getItem(KEY));
  });

  var saved = normalise(localStorage.getItem(KEY));
  var nav = performance.getEntriesByType && performance.getEntriesByType("navigation")[0];
  var cameBack = nav && nav.type === "back_forward";
  if (saved && !cameBack) {
    auto.hidden = false;
    document.getElementById("auto-url").textContent = saved;
    timer = setTimeout(function () {
      open(saved);
    }, 1200);
  } else {
    showForm(saved);
  }
})();
