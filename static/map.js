// Renders the lot grid as SVG: walls, slots (free/occupied/your car), route, "you are here".
const CELL = 24;

function cssVar(name) { return `var(${name})`; }

export function renderMap(svg, lot, status = {}, opts = {}) {
  const rows = lot.grid.length, cols = lot.grid[0].length;
  svg.setAttribute("viewBox", `0 0 ${cols * CELL} ${rows * CELL}`);
  svg.classList.add("map");
  const parts = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const ch = lot.grid[r][c];
      const x = c * CELL, y = r * CELL;
      if (ch === "#") parts.push(`<rect x="${x}" y="${y}" width="${CELL}" height="${CELL}" fill="${cssVar("--wall")}"/>`);
      else parts.push(`<rect x="${x}" y="${y}" width="${CELL}" height="${CELL}" fill="${cssVar("--floor")}"/>`);
    }
  }
  for (const s of lot.slots) {
    const occupied = status[s.slot_id ?? s.id];
    const mine = opts.highlight === s.id;
    const fill = mine ? "--mine" : occupied ? "--occupied" : "--free";
    parts.push(`<rect x="${s.col * CELL + 2}" y="${s.row * CELL + 2}" width="${CELL - 4}" height="${CELL - 4}" rx="3"
      fill="${cssVar(fill)}"><title>${s.id}${occupied ? " (occupied)" : " (free)"}</title></rect>`);
    if (mine) {
      parts.push(`<circle cx="${s.col * CELL + CELL / 2}" cy="${s.row * CELL + CELL / 2}" r="${CELL * 0.85}"
        fill="none" stroke="${cssVar("--mine")}" stroke-width="2.5"/>`);
    }
  }
  if (opts.path && opts.path.length > 1) {
    const pts = opts.path.map(([r, c]) => `${c * CELL + CELL / 2},${r * CELL + CELL / 2}`).join(" ");
    parts.push(`<polyline points="${pts}" fill="none" stroke="${cssVar("--path")}" stroke-width="5"
      stroke-linecap="round" stroke-linejoin="round" stroke-dasharray="10 10" class="route-line"/>`);
  }
  for (const p of lot.points) {
    const cx = p.col * CELL + CELL / 2, cy = p.row * CELL + CELL / 2;
    const here = opts.from === p.id;
    parts.push(`<circle cx="${cx}" cy="${cy}" r="${here ? 9 : 7}" fill="${cssVar(here ? "--accent" : "--muted")}"
      stroke="${cssVar("--surface")}" stroke-width="2"><title>${p.name}</title></circle>`);
    if (here) {
      const tx = Math.min(Math.max(cx, 70), cols * CELL - 70);
      const ty = p.row < rows / 2 ? cy + 30 : cy - 18;
      parts.push(`<text x="${tx}" y="${ty}" text-anchor="middle" font-size="13" font-weight="700"
        fill="${cssVar("--accent")}">You are here</text>`);
    }
  }
  svg.innerHTML = parts.join("");
}

export function plateHtml(plate) {
  return [...plate].map(ch => ch === "?" ? `<span class="unk">•</span>` : ch).join("");
}
