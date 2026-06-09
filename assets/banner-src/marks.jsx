// marks.jsx — "Conducted Field" visual system for brain_tact
// A single amber baton (the conductor's gesture) resolves a field of cool
// light points from scattered/dim (left) into even, luminous order (right).
// Severe palette: warm charcoal ground · one gold · one cool accent.
// Exports all building blocks + concept marks to window.

// ---------------------------------------------------------------- palette
const BT = {
  ground:   '#151210',   // warm charcoal
  groundHi: '#221c15',   // vignette center
  groundLo: '#0d0b09',   // vignette edge
  gold:     '#E9A53C',   // the baton — the only heat
  goldDeep: '#B5781F',   // weighted grip
  goldTip:  '#FFDD97',   // luminous tip
  cool:     '#7FB0CE',   // ordered light
  coolBright:'#BCE2F4',  // resolved, luminous
  coolDim:  '#3C4E5C',   // scattered, dim
  ink:      '#E7DFD3',   // engineer's lettering
  inkSoft:  '#8A8378',   // quiet labels
};

// deterministic field of light points: scattered+dim left → ordered+bright right
function fieldDots({ x0, x1, y0, y1, cols, rows, seed = 7, dropLeft = 0.45 }) {
  let s = seed * 2654435761 % 2147483647;
  const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
  const ease = t => t * t * (3 - 2 * t);
  const dots = [];
  for (let c = 0; c < cols; c++) {
    const t = cols === 1 ? 1 : c / (cols - 1);     // 0 left → 1 right
    const x = x0 + (x1 - x0) * t;
    for (let r = 0; r < rows; r++) {
      const oy = y0 + (y1 - y0) * (rows === 1 ? 0.5 : r / (rows - 1)); // ordered
      const sy = y0 + (y1 - y0) * rnd();                               // scattered
      const k = ease(t);
      const y = sy + (oy - sy) * k;
      if (t < 0.4 && rnd() < dropLeft) continue;    // sparser on the left
      const jx = (1 - t) * (rnd() - 0.5) * ((x1 - x0) / cols) * 1.5;
      dots.push({
        x: x + jx, y,
        op: 0.16 + 0.78 * t,
        rad: 1.6 + 1.7 * t,
        t,
      });
    }
  }
  return dots;
}

function Field({ x0, x1, y0, y1, cols, rows, seed, dropLeft, glow = true }) {
  const dots = fieldDots({ x0, x1, y0, y1, cols, rows, seed, dropLeft });
  return (
    <g>
      {dots.map((d, i) => {
        const col = d.t > 0.62 ? BT.coolBright : BT.cool;
        return (
          <g key={i}>
            {glow && d.t > 0.55 && (
              <circle cx={d.x} cy={d.y} r={d.rad * 3.2} fill={BT.cool}
                      opacity={0.10 * d.t} />
            )}
            <circle cx={d.x} cy={d.y} r={d.rad} fill={col} opacity={d.op} />
          </g>
        );
      })}
    </g>
  );
}

// the baton: weighted rounded grip → tapering luminous tip, along a diagonal
function Baton({ gx, gy, tx, ty, wg = 13, wt = 1.6, id = 'b', sheen = true, glow = true }) {
  const dx = tx - gx, dy = ty - gy;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;     // along
  const px = -uy, py = ux;                 // perpendicular
  const P = (x, y) => `${x.toFixed(2)},${y.toFixed(2)}`;
  // body quad grip→tip
  const gL = [gx + px * wg, gy + py * wg];
  const gR = [gx - px * wg, gy - py * wg];
  const tL = [tx + px * wt, ty + py * wt];
  const tR = [tx - px * wt, ty - py * wt];
  // tapered body (flat grip edge) — a weighted round grip bulb is drawn on top
  const body = `M ${P(...gL)} L ${P(...tL)} L ${P(...tR)} L ${P(...gR)} Z`;
  // upper-edge sheen
  const sL = [gx + px * (wg * 0.55), gy + py * (wg * 0.55)];
  const sT = [tx + px * (wt * 0.7), ty + py * (wt * 0.7)];
  return (
    <g>
      {glow && (
        <circle cx={tx} cy={ty} r={wg * 3.4} fill={`url(#${id}-tipglow)`} />
      )}
      <defs>
        <linearGradient id={`${id}-body`} x1={gx} y1={gy} x2={tx} y2={ty}
                        gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor={BT.goldDeep} />
          <stop offset="0.55" stopColor={BT.gold} />
          <stop offset="1" stopColor={BT.goldTip} />
        </linearGradient>
        <radialGradient id={`${id}-tipglow`}>
          <stop offset="0" stopColor={BT.goldTip} stopOpacity="0.55" />
          <stop offset="0.5" stopColor={BT.gold} stopOpacity="0.16" />
          <stop offset="1" stopColor={BT.gold} stopOpacity="0" />
        </radialGradient>
      </defs>
      <path d={body} fill={`url(#${id}-body)`} />
      {/* weighted, rounded grip bulb */}
      <circle cx={gx} cy={gy} r={wg} fill={`url(#${id}-body)`} />
      <circle cx={gx - ux * wg * 0.18} cy={gy - uy * wg * 0.18} r={wg * 0.62}
              fill={BT.goldDeep} opacity="0.55" />
      {sheen && (
        <path d={`M ${P(...sL)} L ${P(...sT)}`} stroke={BT.goldTip}
              strokeOpacity="0.5" strokeWidth={wg * 0.16} strokeLinecap="round" fill="none" />
      )}
      {/* luminous tip point */}
      <circle cx={tx} cy={ty} r={wt + 1.6} fill={BT.goldTip} />
    </g>
  );
}

// square icon frame: warm charcoal, vignette, hairline, optional rounding
function IconFrame({ size = 512, r = 112, children, light = false }) {
  const id = 'f' + Math.round(Math.random() * 1e6);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width="100%" height="100%"
         style={{ display: 'block' }}>
      <defs>
        <radialGradient id={`${id}-bg`} cx="0.42" cy="0.34" r="0.9">
          <stop offset="0" stopColor={light ? '#efe9df' : BT.groundHi} />
          <stop offset="1" stopColor={light ? '#ddd5c7' : BT.groundLo} />
        </radialGradient>
        <clipPath id={`${id}-clip`}>
          <rect x="0" y="0" width={size} height={size} rx={r} ry={r} />
        </clipPath>
      </defs>
      <g clipPath={`url(#${id}-clip)`}>
        <rect x="0" y="0" width={size} height={size} fill={`url(#${id}-bg)`} />
        {children}
        <rect x="1" y="1" width={size - 2} height={size - 2} rx={r - 1} ry={r - 1}
              fill="none" stroke={light ? '#00000018' : '#ffffff14'} strokeWidth="2" />
      </g>
    </svg>
  );
}

// ------------------------------------------------------------- CONCEPT MARKS
// A · Downbeat — full philosophy: diagonal baton over a resolving field
function MarkDownbeat({ light = false }) {
  return (
    <IconFrame light={light}>
      <Field x0={86} x1={430} y0={318} y1={452} cols={9} rows={4} seed={11} />
      <Baton id="dwn" gx={150} gy={404} tx={402} ty={118} wg={15} wt={1.8} />
    </IconFrame>
  );
}

// B · Tempo — metronome: clean progression, generous void, 3 rows
function MarkTempo({ light = false }) {
  return (
    <IconFrame light={light}>
      <Field x0={104} x1={418} y0={300} y1={420} cols={7} rows={3} seed={5} dropLeft={0.55} />
      <Baton id="tmp" gx={168} gy={372} tx={372} ty={150} wg={13} wt={1.5} />
    </IconFrame>
  );
}

// C · The Tip — extreme restraint: baton + a single resolved point
function MarkTip({ light = false }) {
  const ghosts = [[120, 360, .14], [150, 300, .1], [128, 250, .08], [180, 392, .12]];
  return (
    <IconFrame light={light}>
      {ghosts.map((g, i) => (
        <circle key={i} cx={g[0]} cy={g[1]} r="3" fill={BT.coolDim} opacity={g[2]} />
      ))}
      <circle cx="388" cy="360" r="26" fill={BT.cool} opacity="0.12" />
      <circle cx="388" cy="360" r="6.5" fill={BT.coolBright} />
      <circle cx="388" cy="360" r="13" fill="none" stroke={BT.cool} strokeWidth="1.4" opacity="0.5" />
      <Baton id="tip" gx={150} gy={392} tx={372} ty={158} wg={14} wt={1.6} />
    </IconFrame>
  );
}

// D · Conducted Rows — gesture trail + points sorted into clean lanes
function MarkRows({ light = false }) {
  const lanes = [330, 372, 414];
  return (
    <IconFrame light={light}>
      {/* faint calligraphic trail of the gesture */}
      <path d="M 150 404 Q 250 300 402 118" fill="none"
            stroke={BT.gold} strokeOpacity="0.14" strokeWidth="22" strokeLinecap="round" />
      {/* scattered, dim on the left */}
      <Field x0={92} x1={232} y0={312} y1={432} cols={4} rows={3} seed={9} dropLeft={0.3} glow={false} />
      {/* resolved into 3 even lanes on the right */}
      {lanes.map((y, li) =>
        [0, 1, 2, 3].map((c) => {
          const x = 286 + c * 42;
          const t = 0.6 + c * 0.12;
          return <circle key={li + '-' + c} cx={x} cy={y} r={2.6 + c * 0.5}
                         fill={c > 1 ? BT.coolBright : BT.cool} opacity={0.5 + c * 0.13} />;
        })
      )}
      <Baton id="row" gx={150} gy={404} tx={402} ty={118} wg={15} wt={1.8} />
    </IconFrame>
  );
}

Object.assign(window, {
  BT, Field, Baton, IconFrame,
  MarkDownbeat, MarkTempo, MarkTip, MarkRows,
});
