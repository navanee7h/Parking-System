import { renderFloor, plateHtml } from "/static/map.js";

const $ = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
let lot, status = {}, lastMatch = null;

async function getJSON(url) {
  const r = await fetch(url);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || r.statusText);
  return body;
}

const floorName = id => lot.floors.find(f => f.id === id)?.name ?? id;

async function init() {
  lot = await getJSON("/api/lot");
  $("lot-name").textContent = lot.name;
  const order = { kiosk: 0, lift: 1, stairs: 2, gate: 3 };
  const groups = {};
  for (const p of lot.points) (groups[p.floor] ||= []).push(p);
  $("from").innerHTML = lot.floors.map(f => `<optgroup label="${f.name}">` +
    (groups[f.id] || []).sort((a, b) => order[a.kind] - order[b.kind] || a.id.localeCompare(b.id))
      .map(p => `<option value="${p.id}">${p.name}</option>`).join("") + `</optgroup>`).join("");
  const wanted = params.get("kiosk") || params.get("from");
  if (lot.points.some(p => p.id === wanted)) $("from").value = wanted;
  $("from").onchange = $("lifts-only").onchange = () => lastMatch && showRoute(lastMatch);
  const s = await getJSON("/api/slots");
  status = Object.fromEntries(s.slots.map(x => [x.slot_id, x.occupied]));
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
      <span class="badge">${m.exact ? "Exact match" : Math.round(m.score * 100) + "% match"} · ${m.floor_name} · ${m.slot_id}</span>
    </button></li>`).join("");
  box.querySelectorAll("button").forEach(b => b.onclick = () => showRoute(res.results[+b.dataset.i]));
  if (res.exact && res.results.length === 1) showRoute(res.results[0]);
}

async function showRoute(match) {
  lastMatch = match;
  const from = $("from").value;
  let r;
  try {
    r = await getJSON(`/api/route?from=${encodeURIComponent(from)}&slot=${encodeURIComponent(match.slot_id)}` +
      ($("lifts-only").checked ? "&lifts_only=true" : ""));
  } catch (e) {
    $("result").classList.remove("hidden");
    $("title").textContent = "Can't plan a route";
    $("summary").textContent = e.message;
    $("maps").innerHTML = ""; $("steps").innerHTML = "";
    return;
  }
  $("result").classList.remove("hidden");
  $("title").textContent = `${match.floor_name} · Slot ${match.slot_id}`;
  $("summary").innerHTML = `<span class="plate">${plateHtml(match.plate)}</span> · about ${Math.round(r.distance_m)} m walk`;
  $("steps").innerHTML = r.steps.map(s => `<li class="${/^Take (lift|stairs)/.test(s) ? "step-hop" : ""}">${s}</li>`).join("");
  const warn = $("partial-warn");
  if (match.plate.includes("?") || match.read_confidence < 0.7) {
    warn.textContent = "The camera could only partly read this plate. Please check it's your car when you get there.";
    warn.classList.remove("hidden");
  } else warn.classList.add("hidden");

  const maps = $("maps");
  maps.innerHTML = "";
  for (const [i, leg] of r.legs.entries()) {
    const last = i === r.legs.length - 1;
    const hop = (r.steps.find(s => /^Take (lift|stairs) /.test(s)) || "").match(/^Take (lift|stairs) (\S+)/);
    const head = r.legs.length === 1 ? floorName(leg.floor)
      : `${i + 1}. ${floorName(leg.floor)} – ${last ? "walk to your car" : `walk to ${hop ? hop[1] + " " + hop[2] : "the lift"}`}`;
    const wrap = document.createElement("div");
    wrap.innerHTML = `<div class="map-head"><h3>${head}</h3><button class="btn">Whole floor</button></div>
      <div class="map-wrap"><svg role="img" aria-label="Map of ${floorName(leg.floor)} with your route"></svg></div>`;
    maps.appendChild(wrap);
    const svg = wrap.querySelector("svg"), btn = wrap.querySelector("button");
    const lotPointAt = xy => lot.points.find(p => p.floor === leg.floor && Math.hypot(p.x - xy[0], p.y - xy[1]) < 0.5);
    const opts = {
      path: leg.path,
      highlight: last ? match.slot_id : null,
      from: i === 0 ? from : null,
      to: !last ? lotPointAt(leg.path.at(-1))?.id : i > 0 ? lotPointAt(leg.path[0])?.id : null,
      zoom: "route",
    };
    await renderFloor(svg, lot, leg.floor, status, opts);
    btn.onclick = async () => {
      opts.zoom = opts.zoom === "route" ? "floor" : "route";
      btn.textContent = opts.zoom === "route" ? "Whole floor" : "Zoom to route";
      await renderFloor(svg, lot, leg.floor, status, opts);
    };
  }
  $("result").scrollIntoView({ behavior: "smooth", block: "start" });
}

init().catch(e => { $("lot-name").textContent = "Could not load the parking map: " + e.message; });
