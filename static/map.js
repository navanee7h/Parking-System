// Draws one floor: the plan drawing, slots (free / occupied / your car), points and a route.
const drawingCache = {};

export async function getFloorDrawing(floorId) {
  if (!drawingCache[floorId]) {
    drawingCache[floorId] = fetch(`/api/floors/${encodeURIComponent(floorId)}`).then(r => r.json());
  }
  return drawingCache[floorId];
}

const STROKE = { line: "var(--plan-line)", faint: "var(--plan-faint)", accent: "var(--plan-accent)" };
const FILL = { line: "var(--plan-line)", faint: "var(--plan-faint)", accent: "var(--plan-accent)", wall: "var(--wall)" };
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function drawingSvg(d) {
  const byStyle = {};
  for (const sh of d.shapes) {
    const p = sh.p;
    let path = `M${p[0]} ${p[1]}`;
    for (let i = 2; i < p.length; i += 2) path += `L${p[i]} ${p[i + 1]}`;
    if (sh.z) path += "Z";
    (byStyle[sh.s] ||= []).push(path);
  }
  let out = "";
  for (const [s, paths] of Object.entries(byStyle)) {
    const st = d.styles[s];
    const fill = st.fill ? FILL[st.fill] : "none";
    const stroke = st.stroke ? STROKE[st.stroke] : "none";
    const w = st.stroke === "faint" ? 0.6 : 1;
    out += `<path d="${paths.join("")}" fill="${fill}" stroke="${stroke}" stroke-width="${w}"
      vector-effect="non-scaling-stroke" stroke-linecap="round"/>`;
  }
  for (const t of d.texts) {
    const rot = t.rot ? ` transform="rotate(${t.rot} ${t.x} ${t.y})"` : "";
    out += `<text x="${t.x}" y="${t.y}" font-size="${t.size}" fill="var(--plan-text)"${rot}>${esc(t.t)}</text>`;
  }
  return out;
}

function fitBox(floor, pts) {
  const [bx0, by0, bx1, by1] = floor.bounds;
  if (!pts.length) return [bx0, by0, bx1 - bx0, by1 - by0];
  const pad = floor.marker[0] * 2.5, minW = floor.marker[0] * 12;
  let x0 = Math.min(...pts.map(p => p[0])) - pad, x1 = Math.max(...pts.map(p => p[0])) + pad;
  let y0 = Math.min(...pts.map(p => p[1])) - pad, y1 = Math.max(...pts.map(p => p[1])) + pad;
  // keep the floor's aspect ratio so the map doesn't jump in height
  const aspect = (by1 - by0) / (bx1 - bx0);
  let w = Math.max(x1 - x0, minW, (y1 - y0) / aspect), h = w * aspect;
  w = Math.min(w, bx1 - bx0); h = Math.min(h, by1 - by0);
  let cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  cx = Math.min(Math.max(cx, bx0 + w / 2), bx1 - w / 2);
  cy = Math.min(Math.max(cy, by0 + h / 2), by1 - h / 2);
  return [cx - w / 2, cy - h / 2, w, h];
}

/**
 * opts: { highlight: slotId, path: [[x,y]...], from: pointId, to: pointId, zoom: "route" | "floor" }
 */
export async function renderFloor(svg, lot, floorId, status = {}, opts = {}) {
  const floor = lot.floors.find(f => f.id === floorId);
  const drawing = await getFloorDrawing(floorId);
  const [mw, mh] = floor.marker;
  const parts = [`<rect x="${floor.bounds[0]}" y="${floor.bounds[1]}" width="${floor.bounds[2] - floor.bounds[0]}"
    height="${floor.bounds[3] - floor.bounds[1]}" fill="var(--floor)"/>`, drawingSvg(drawing)];

  let mine = null;
  for (const s of lot.slots) {
    if (s.floor !== floorId) continue;
    const isMine = opts.highlight === s.id;
    if (isMine) mine = s;
    const fill = isMine ? "var(--mine)" : status[s.id] ? "var(--occupied)" : "var(--free)";
    parts.push(`<rect x="${s.x - mw / 2}" y="${s.y - mh / 2}" width="${mw}" height="${mh}" rx="${mh * 0.2}"
      fill="${fill}" opacity="${isMine ? 1 : 0.85}"><title>${esc(s.id)} – ${status[s.id] ? "occupied" : "free"}</title></rect>`);
    if (mw >= 4) {
      parts.push(`<text x="${s.x}" y="${s.y + mh * 0.22}" font-size="${mh * 0.62}" text-anchor="middle"
        fill="${isMine ? "#fff" : "var(--slot-text)"}" font-weight="${isMine ? 700 : 500}">${esc(s.id)}</text>`);
    }
  }
  if (mine) {
    parts.push(`<circle cx="${mine.x}" cy="${mine.y}" r="${mw * 0.9}" fill="none" stroke="var(--mine)"
      stroke-width="3" vector-effect="non-scaling-stroke"/>`);
  }
  if (opts.path && opts.path.length > 1) {
    const pts = opts.path.map(([x, y]) => `${x},${y}`).join(" ");
    parts.push(`<polyline points="${pts}" fill="none" stroke="var(--path)" stroke-width="5"
      stroke-linecap="round" stroke-linejoin="round" vector-effect="non-scaling-stroke"
      stroke-dasharray="10 8" class="route-line"/>`);
  }
  const focus = [];
  if (opts.zoom !== "floor") {
    (opts.path || []).forEach(p => focus.push(p));
    if (mine) focus.push([mine.x, mine.y]);
  }
  const box = fitBox(floor, focus);
  const r = mh * 0.75;
  for (const p of lot.points) {
    if (p.floor !== floorId) continue;
    const here = opts.from === p.id, to = opts.to === p.id;
    const col = here ? "var(--accent)" : to ? "var(--path)" : "var(--muted)";
    const letter = p.kind === "lift" ? "L" : p.kind === "stairs" ? "S" : p.kind === "gate" ? "G" : "Q";
    parts.push(`<g><title>${esc(p.name)}</title><circle cx="${p.x}" cy="${p.y}" r="${here || to ? r * 1.4 : r}"
      fill="${col}" stroke="var(--surface)" stroke-width="1.5" vector-effect="non-scaling-stroke"/>
      ${mw >= 4 ? `<text x="${p.x}" y="${p.y + r * 0.4}" font-size="${r * 1.1}" text-anchor="middle" fill="#fff" font-weight="700">${letter}</text>` : ""}</g>`);
    if (here || to) {
      const label = here ? "You are here" : esc(p.id);
      const rel = (p.x - box[0]) / box[2];
      const anchor = rel > 0.7 ? "end" : rel < 0.3 ? "start" : "middle";
      const lx = anchor === "end" ? p.x + r : anchor === "start" ? p.x - r : p.x;
      const ly = (p.y - box[1]) / box[3] < 0.15 ? p.y + r * 3.2 : p.y - r * 2;
      parts.push(`<text x="${lx}" y="${ly}" font-size="${mh * 1.1}" text-anchor="${anchor}" font-weight="700"
        fill="${col}" stroke="var(--surface)" stroke-width="3" paint-order="stroke"
        vector-effect="non-scaling-stroke">${label}</text>`);
    }
  }

  svg.setAttribute("viewBox", box.join(" "));
  svg.classList.add("map");
  svg.innerHTML = parts.join("");
}

export function plateHtml(plate) {
  return [...plate].map(ch => ch === "?" ? `<span class="unk">•</span>` : esc(ch)).join("");
}
