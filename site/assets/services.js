// Loads the service list from the cluster (URL in <meta name="services">) and renders it.
// If the cluster does not answer, the page still works and the list says so.
(function () {
  var meta = document.querySelector('meta[name="services"]');
  var section = document.querySelector(".services");
  if (!meta || !section) return;
  var list = section.querySelector(".list");
  var STATUS = { up: "up", degraded: "slow or unexpected answer", down: "down" };
  var shown = false; // a list came through at least once
  var last = ""; // the list as last drawn
  var loaded = 0; // when the last answer came in

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text) n.textContent = text;
    return n;
  }

  function render(services) {
    // The list is a live region: redrawing the same list every minute would read it out again.
    var key = JSON.stringify(services);
    if (key === last && !list.querySelector(".note")) return;
    last = key;
    list.textContent = "";
    shown = true;
    var group = null, ul = null;
    services.forEach(function (s) {
      if (!/^https?:\/\//.test(s.url || "")) return;
      if (ul === null || s.group !== group) {
        group = s.group;
        if (group) list.appendChild(el("p", "group", group));
        ul = list.appendChild(el("ul"));
      }
      var li = ul.appendChild(el("li"));
      var a = li.appendChild(el("a"));
      a.href = s.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      var name = a.appendChild(el("span", "name"));
      if (STATUS[s.status]) {
        var led = name.appendChild(el("span", "led " + s.status));
        led.title = STATUS[s.status];
        name.appendChild(el("span", "sr", STATUS[s.status] + ": "));
      }
      name.appendChild(document.createTextNode(s.name || ""));
      var host = s.url;
      try { host = new URL(s.url).host; } catch (e) {}
      a.appendChild(el("span", "url", host));
      if (s.description) li.appendChild(el("span", "what", s.description));
    });
    section.hidden = !list.firstChild;
  }

  function load() {
    var ctrl = window.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 6000);
    fetch(meta.content, { cache: "no-store", signal: ctrl && ctrl.signal })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        loaded = Date.now();
        render(Array.isArray(data && data.services) ? data.services : []);
      })
      .catch(function () {
        // A blip after a good load keeps the list (links still work) and only adds the note.
        if (!shown) list.textContent = "";
        if (list.querySelector(".note")) return;
        list.insertBefore(el("p", "note", shown ? "% cluster unreachable, showing the last list" : "% cluster unreachable, services may be down"), list.firstChild);
        section.hidden = false;
      })
      .then(function () { clearTimeout(timer); });
  }

  load();
  setInterval(function () { if (!document.hidden) load(); }, 60000);
  // Back on a tab left in the background: don't show minutes-old LEDs until the next tick.
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden && Date.now() - loaded > 60000) load();
  });
})();
