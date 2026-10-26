(function () {
  var lv = (navigator.languages || [navigator.language || ""]).some(function (l) {
    return String(l).toLowerCase().indexOf("lv") === 0;
  });
  if (lv) {
    document.documentElement.lang = "lv";
    document.getElementById("title").textContent = "Serveris nav sasniedzams";
    document.getElementById("body").textContent =
      "Kameru panelis nav sasniedzams. Pārbaudiet tīkla vai VPN savienojumu.";
    document.getElementById("retry").textContent = "Mēģināt vēlreiz";
  }
  document.getElementById("retry").addEventListener("click", function () {
    location.reload();
  });
  window.addEventListener("online", function () {
    location.reload();
  });
})();
