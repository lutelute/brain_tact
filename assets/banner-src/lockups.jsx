// lockups.jsx — wordmark lockups + banners built on the Conducted Field system
// Relies on globals from marks.jsx: BT, Field, Baton.

const MONO = "'JetBrains Mono', ui-monospace, monospace";

// compact transparent mark for lockups (no frame)
function GlyphMark({ size = 200 }) {
  return (
    <svg viewBox="0 0 200 200" width={size} height={size} style={{ display: 'block' }}>
      <Field x0={36} x1={170} y0={120} y1={176} cols={7} rows={3} seed={11} dropLeft={0.5} />
      <Baton id="gly" gx={56} gy={158} tx={160} ty={44} wg={9.5} wt={1.2} />
    </svg>
  );
}

// horizontal wordmark lockup
function Wordmark({ tagline = true, light = false }) {
  const ink = light ? '#1a1714' : BT.ink;
  const soft = light ? '#7a7264' : BT.inkSoft;
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 22,
      padding: '34px 40px',
      background: light
        ? 'radial-gradient(120% 140% at 30% 30%, #efe9df, #ddd5c7)'
        : `radial-gradient(120% 140% at 30% 30%, ${BT.groundHi}, ${BT.groundLo})`,
      borderRadius: 18, width: 'max-content',
    }}>
      <GlyphMark size={104} />
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <div style={{ fontFamily: MONO, fontSize: 46, fontWeight: 700, letterSpacing: '-0.01em', color: ink, lineHeight: 1 }}>
          <span style={{ color: BT.gold }}>brain</span><span style={{ color: soft }}>_</span><span>tact</span>
        </div>
        {tagline && (
          <div style={{ fontFamily: MONO, fontSize: 13, letterSpacing: '0.26em', textTransform: 'uppercase', color: soft }}>
            chaos, cooled into tempo
          </div>
        )}
      </div>
    </div>
  );
}

// stacked wordmark (mark on top, name + tagline below) — good for square/avatar contexts
function WordmarkStacked() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18,
      padding: '46px 56px',
      background: `radial-gradient(120% 120% at 50% 34%, ${BT.groundHi}, ${BT.groundLo})`,
      borderRadius: 18, width: 'max-content',
    }}>
      <GlyphMark size={132} />
      <div style={{ fontFamily: MONO, fontSize: 40, fontWeight: 700, letterSpacing: '-0.01em', color: BT.ink }}>
        <span style={{ color: BT.gold }}>brain</span><span style={{ color: BT.inkSoft }}>_</span><span>tact</span>
      </div>
      <div style={{ fontFamily: MONO, fontSize: 11.5, letterSpacing: '0.3em', textTransform: 'uppercase', color: BT.inkSoft }}>
        a conductor for your sessions
      </div>
    </div>
  );
}

// shared banner background
function BannerBG({ w, h, id }) {
  return (
    <g>
      <defs>
        <radialGradient id={`${id}-bg`} cx="0.32" cy="0.3" r="1.0">
          <stop offset="0" stopColor={BT.groundHi} />
          <stop offset="1" stopColor={BT.groundLo} />
        </radialGradient>
      </defs>
      <rect x="0" y="0" width={w} height={h} fill={`url(#${id}-bg)`} />
    </g>
  );
}

// GitHub social card 1280×640
function BannerSocial() {
  const w = 1280, h = 640;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height="100%" style={{ display: 'block' }}>
      <BannerBG w={w} h={h} id="soc" />
      <Field x0={660} x1={1185} y0={360} y1={540} cols={13} rows={5} seed={23} dropLeft={0.5} />
      <Baton id="soc" gx={560} gy={470} tx={1120} ty={150} wg={18} wt={2} />
      {/* wordmark, left column, fully legible */}
      <text x="120" y="300" fontFamily={MONO} fontSize="92" fontWeight="700" letterSpacing="-2">
        <tspan fill={BT.gold}>brain</tspan><tspan fill={BT.inkSoft}>_</tspan><tspan fill={BT.ink}>tact</tspan>
      </text>
      <text x="126" y="350" fontFamily={MONO} fontSize="21" letterSpacing="7.5" fill={BT.inkSoft}>
        CHAOS, COOLED INTO TEMPO
      </text>
      <line x1="126" y1="378" x2="360" y2="378" stroke={BT.gold} strokeWidth="2" opacity="0.55" />
      <text x="126" y="424" fontFamily={MONO} fontSize="17" letterSpacing="2" fill={BT.inkSoft} opacity="0.72">
        完了を疑い、改善ループを止めさせない監督
      </text>
    </svg>
  );
}

// README header banner 1280×320 (wide, short)
function BannerReadme() {
  const w = 1280, h = 320;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height="100%" style={{ display: 'block' }}>
      <BannerBG w={w} h={h} id="rdm" />
      <Field x0={640} x1={1190} y0={150} y1={262} cols={13} rows={4} seed={31} dropLeft={0.5} />
      <Baton id="rdm" gx={560} gy={236} tx={1090} ty={66} wg={13} wt={1.6} />
      <text x="92" y="150" fontFamily={MONO} fontSize="62" fontWeight="700" letterSpacing="-1.5">
        <tspan fill={BT.gold}>brain</tspan><tspan fill={BT.inkSoft}>_</tspan><tspan fill={BT.ink}>tact</tspan>
      </text>
      <text x="96" y="186" fontFamily={MONO} fontSize="15" letterSpacing="6" fill={BT.inkSoft}>
        CHAOS, COOLED INTO TEMPO
      </text>
      <text x="96" y="238" fontFamily={MONO} fontSize="14.5" letterSpacing="1.5" fill={BT.inkSoft} opacity="0.7">
        a critique-first supervisor for Claude Code sessions
      </text>
    </svg>
  );
}

Object.assign(window, { GlyphMark, Wordmark, WordmarkStacked, BannerSocial, BannerReadme });
