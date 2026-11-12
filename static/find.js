import { renderMap, plateHtml } from "/static/map.js";

const $ = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
let lot, status = {};
let from = params.get("kiosk") || params.get("from");

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
  return r.json();
}

async function init() {
  lot = await getJSON("/api/lot");
  const kiosks = lot.points.filter(p => p.kind === "kiosk");
  const known = lot.points.find(p => p.id === from);
  if (known) {
    $("where").textContent = `You are at: ${known.name}. Type your number plate.`;
  } else {
    from = kiosks[0]?.id;
    $("location-card").hidden = false;
    $("from").innerHTML = kiosks.map(k => `<option value="${k.id}">${k.name}</option>`).join("");
    $("from").onchange = e => { from = e.target.value; };
  }
  const s = await getJSON("/api/slots");
  status = Object.fromEntries(s.slots.map(x => [x.slot_id, x.occupied]));
  renderMap($("map"), lot, status, { from });
}

let timer;
$("plate").addEventListener("input", e => {
  clearTimeout(timer);
  timer = setTimeout(() => search(e.target.value), 200);
});
$("plate").addEventListener("keydown", e => {
  if (e.key === "Enter") { const b = $("suggestions").querySelector("button"); if (b) b.click(); }
});

async function search(q) {
  const box = $("suggestions");
  const clean = q.toUpperCase().replace(/[^A-Z0-9?*]/g, "");
  if (clean.replace(/[?*]/g, "").length < 3) { box.innerHTML = ""; return; }
  const res = await getJSON(`/api/search?q=${encodeURIComponent(q)}`);
  if (!res.results.length) {
    box.innerHTML = `<li class="hint">No matching car yet. Check the plate, or try fewer characters.</li>`;
    return;
  }
  const label = res.exact ? "" : `<li class="hint">Did you mean one of these?</li>`;
  box.innerHTML = label + res.results.map((m, i) => `
    <li><button data-i="${i}">
      <span class="plate">${plateHtml(m.plate)}</span>
      <span class="badge">${m.exact ? "Exact match" : Math.round(m.score * 100) + "% match"} · slot ${m.slot_id}</span>
    </button></li>`).join("");
  box.querySelectorAll("button").forEach(b =>
    b.onclick = () => showRoute(res.results[+b.dataset.i]));
  if (res.exact && res.results.length === 1) showRoute(res.results[0]);
}

async function showRoute(match) {
  const r = await getJSON(`/api/route?from=${encodeURIComponent(from)}&slot=${encodeURIComponent(match.slot_id)}`);
  $("result").classList.remove("hidden");
  $("slot").textContent = match.slot_id;
  $("summary").innerHTML = `<span class="plate">${plateHtml(match.plate)}</span> · about ${Math.round(r.distance_m)} m walk`;
  $("steps").innerHTML = r.steps.map(s => `<li>${s}</li>`).join("");
  const warn = $("partial-warn");
  if (match.plate.includes("?") || match.read_confidence < 0.7) {
    warn.textContent = "The camera could only partly read this plate. Please check it's your car when you get there.";
    warn.classList.remove("hidden");
  } else warn.classList.add("hidden");
  renderMap($("map"), lot, status, { from, highlight: match.slot_id, path: r.path });
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

init().catch(e => { $("where").textContent = "Could not load the parking map: " + e.message; });
