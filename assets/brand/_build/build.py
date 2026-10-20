import os, math, io, base64
import cairosvg
from textpath import text_path, metrics

OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SVG_DIR = os.path.join(OUT, 'svg'); PNG_DIR = os.path.join(OUT, 'png'); FAV_DIR = os.path.join(OUT, 'favicon')
for d in (SVG_DIR, PNG_DIR, FAV_DIR): os.makedirs(d, exist_ok=True)

# ---------------- palette ----------------
TEAL      = '#14B8A6'  # primary
TEAL_DARK = '#0F766E'  # text-on-white teal
TEAL_TINT = '#CCFBF1'  # light tint
INK       = '#0F172A'  # ink navy
OFFWHITE  = '#F8FAFC'  # off-white background
SLATE     = '#64748B'  # muted secondary (labels on sheet)

def lum(h):
    h = h.lstrip('#'); c = [int(h[i:i+2], 16)/255 for i in (0, 2, 4)]
    c = [x/12.92 if x <= 0.04045 else ((x+0.055)/1.055)**2.4 for x in c]
    return 0.2126*c[0] + 0.7152*c[1] + 0.0722*c[2]
def contrast(a, b):
    la, lb = sorted([lum(a), lum(b)], reverse=True); return (la+0.05)/(lb+0.05)

# ---------------- icon geometry (256 x 168 units) ----------------
ICON_W, ICON_H = 256, 156
STROKE = 8        # frame + connector weight
GAP = 4           # clearance between plug and socket
CY = 78
def icon_elems(frame, fill):
    # socket: circle center (142,84), r = plug r (9) + gap (4) = 13; channel half-height = 4 + 4 = 8
    sr, cx, ch = 13, 142, 8
    dx = math.sqrt(sr*sr - ch*ch); ax = cx + dx
    t, b = CY-32, CY+32
    mid = (f'M110 {t}H150A12 12 0 0 1 162 {t+12}V{CY-ch}H{ax:.3f}'
           f'A{sr} {sr} 0 1 0 {ax:.3f} {CY+ch}H162V{b-12}A12 12 0 0 1 150 {b}'
           f'H110A12 12 0 0 1 98 {b-12}V{t+12}A12 12 0 0 1 110 {t}Z')
    return (f'<rect x="4" y="4" width="248" height="{ICON_H-8}" rx="28" fill="none" stroke="{frame}" stroke-width="{STROKE}"/>'
            f'<g fill="{fill}">'
            f'<rect x="42" y="{CY-18}" width="36" height="36" rx="8"/>'
            f'<rect x="76" y="{CY-STROKE/2}" width="24" height="{STROKE}"/>'
            f'<path d="{mid}"/>'
            f'<circle cx="{cx}" cy="{CY}" r="9"/>'
            f'<rect x="{cx}" y="{CY-STROKE/2}" width="42" height="{STROKE}"/>'
            f'<rect x="182" y="{CY-18}" width="36" height="36" rx="8"/>'
            f'</g>')

# ---------------- favicon geometry ----------------
def fav32_elems(tile=INK, fill=TEAL):
    # pixel-snapped 32px grid: socket is a square cut with a uniform 1px clearance around a 4px plug
    mid = ('M12.5 10H19.5A2.5 2.5 0 0 1 22 12.5V14H21V13H15V19H21V18H22V19.5A2.5 2.5 0 0 1 19.5 22'
           'H12.5A2.5 2.5 0 0 1 10 19.5V12.5A2.5 2.5 0 0 1 12.5 10Z')
    return (f'<rect width="32" height="32" rx="7" fill="{tile}"/><g fill="{fill}">'
            f'<rect x="2" y="13" width="6" height="6" rx="1.5"/><rect x="7.5" y="15" width="3" height="2"/>'
            f'<path d="{mid}"/><rect x="16" y="14" width="4" height="4" rx="1"/><rect x="19.5" y="15" width="5" height="2"/>'
            f'<rect x="24" y="13" width="6" height="6" rx="1.5"/></g>')
def fav16_elems(tile=INK, fill=TEAL):
    # pixel-snapped 16px grid: every edge on an integer pixel; corner pixels dropped to read as rounded
    return (f'<rect width="16" height="16" rx="3" fill="{tile}"/><g fill="{fill}">'
            f'<rect x="1" y="6" width="3" height="4"/><rect x="4" y="7" width="1" height="2"/>'
            f'<path d="M6 5H10V6H11V10H10V11H6V10H5V6H6Z"/><rect x="11" y="7" width="1" height="2"/>'
            f'<rect x="12" y="6" width="3" height="4"/></g>')
def app_icon_elems(size=320, tile=INK):
    # large favicon / touch icon: full icon (with guardrail frame) on navy tile
    s = 0.78*size/ICON_W; tx = (size - ICON_W*s)/2; ty = (size - ICON_H*s)/2
    return (f'<rect width="{size}" height="{size}" rx="{size*0.22}" fill="{tile}"/>'
            f'<g transform="translate({tx:.3f} {ty:.3f}) scale({s:.5f})">{icon_elems(TEAL, TEAL)}</g>')

# ---------------- wordmark ----------------
WM_FONT = 'manrope600'; WM_TRACK = -0.01
def wordmark(size, color, x, baseline):
    d, adv, (x0, y0, x1, y1) = text_path('minifactory', WM_FONT, size, tracking=WM_TRACK)
    return (f'<path transform="translate({x - x0:.3f} {baseline:.3f})" fill="{color}" d="{d}"/>',
            x1 - x0, y0, y1)

def svg_doc(vb, body, w=None, h=None, title='minifactory'):
    x, y, W, H = vb
    wh = f' width="{w}" height="{h}"' if w else ''
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x:g} {y:g} {W:g} {H:g}"{wh} role="img" aria-label="{title}">'
            f'<title>{title}</title>{body}</svg>\n')

PAD = 24
def horizontal(wm_color, frame=TEAL, fill=TEAL):
    F = 112; xh = metrics(WM_FONT, F)['xh']
    baseline = CY + xh/2
    gap = 44
    p, ww, y0, y1 = wordmark(F, wm_color, ICON_W + gap, baseline)
    W = ICON_W + gap + ww
    body = f'<g>{icon_elems(frame, fill)}</g>{p}'
    return (-PAD, -PAD, W + 2*PAD, ICON_H + 2*PAD), body
def stacked(wm_color, frame=TEAL, fill=TEAL):
    F = 84
    d, adv, (x0, y0, x1, y1) = text_path('minifactory', WM_FONT, F, tracking=WM_TRACK)
    ww = x1 - x0
    W = max(ww, ICON_W)
    gap = 40
    baseline = ICON_H + gap - y0
    p, _, _, _ = wordmark(F, wm_color, (W - ww)/2, baseline)
    body = f'<g transform="translate({(W-ICON_W)/2:.3f} 0)">{icon_elems(frame, fill)}</g>{p}'
    return (-PAD, -PAD, W + 2*PAD, baseline + y1 + 2*PAD), body
def icon_only(frame=TEAL, fill=TEAL):
    return (-PAD/2, -PAD/2, ICON_W + PAD, ICON_H + PAD), icon_elems(frame, fill)

def write(name, vb, body, png_w=2048, title='minifactory logo'):
    svg = svg_doc(vb, body, title=title)
    open(os.path.join(SVG_DIR, name + '.svg'), 'w').write(svg)
    cairosvg.svg2png(bytestring=svg.encode(), write_to=os.path.join(PNG_DIR, name + '.png'), output_width=png_w)
    return svg

ASSETS = {}
ASSETS['minifactory-horizontal-light'] = horizontal(INK)
ASSETS['minifactory-horizontal-dark']  = horizontal(OFFWHITE)
ASSETS['minifactory-stacked-light']    = stacked(INK)
ASSETS['minifactory-stacked-dark']     = stacked(OFFWHITE)
ASSETS['minifactory-icon-light']       = icon_only()
ASSETS['minifactory-icon-dark']        = icon_only()   # teal reads on both; kept as named pair
ASSETS['minifactory-icon-mono-navy']   = icon_only(INK, INK)
ASSETS['minifactory-icon-mono-white']  = icon_only('#FFFFFF', '#FFFFFF')
for n, (vb, body) in ASSETS.items():
    write(n, vb, body)

# favicons
fav16 = svg_doc((0, 0, 16, 16), fav16_elems(), 16, 16, 'minifactory')
fav32 = svg_doc((0, 0, 32, 32), fav32_elems(), 32, 32, 'minifactory')
favapp = svg_doc((0, 0, 320, 320), app_icon_elems(320), 320, 320, 'minifactory')
open(os.path.join(FAV_DIR, 'favicon-16.svg'), 'w').write(fav16)
open(os.path.join(FAV_DIR, 'favicon.svg'), 'w').write(fav32)
open(os.path.join(FAV_DIR, 'app-icon.svg'), 'w').write(favapp)
cairosvg.svg2png(bytestring=fav16.encode(), write_to=os.path.join(FAV_DIR, 'favicon-16.png'), output_width=16)
cairosvg.svg2png(bytestring=fav32.encode(), write_to=os.path.join(FAV_DIR, 'favicon-32.png'), output_width=32)
cairosvg.svg2png(bytestring=fav32.encode(), write_to=os.path.join(FAV_DIR, 'favicon-48.png'), output_width=48)
cairosvg.svg2png(bytestring=favapp.encode(), write_to=os.path.join(FAV_DIR, 'favicon-180.png'), output_width=180)
cairosvg.svg2png(bytestring=favapp.encode(), write_to=os.path.join(FAV_DIR, 'favicon-512.png'), output_width=512)
# apple-touch: opaque square (iOS rounds corners itself)
touch = svg_doc((0, 0, 320, 320), f'<rect width="320" height="320" fill="{INK}"/>' +
                f'<g transform="translate({(320-ICON_W*0.78*320/ICON_W)/2:.3f} {(320-ICON_H*0.78*320/ICON_W)/2:.3f}) scale({0.78*320/ICON_W:.5f})">{icon_elems(TEAL, TEAL)}</g>', 320, 320)
cairosvg.svg2png(bytestring=touch.encode(), write_to=os.path.join(FAV_DIR, 'apple-touch-icon-180.png'), output_width=180)
from PIL import Image
ims = [Image.open(os.path.join(FAV_DIR, f'favicon-{s}.png')).convert('RGBA') for s in (16, 32, 48)]
ims[2].save(os.path.join(FAV_DIR, 'favicon.ico'), format='ICO', sizes=[(16, 16), (32, 32), (48, 48)], append_images=ims[:2])

# ---------------- text helper for compositions ----------------
def txt(s, key, size, color, x, baseline, anchor='start', track=0.0):
    d, adv, (x0, y0, x1, y1) = text_path(s, key, size, tracking=track)
    if anchor == 'middle': x = x - adv/2
    elif anchor == 'end': x = x - adv
    return f'<path transform="translate({x:.2f} {baseline:.2f})" fill="{color}" d="{d}"/>'

def place(asset, x, y, w):
    (vx, vy, vw, vh), body = ASSETS[asset]
    s = w / vw
    return f'<g transform="translate({x:.2f} {y:.2f}) scale({s:.5f}) translate({-vx:.3f} {-vy:.3f})">{body}</g>', vh*s

# ---------------- GitHub social preview 1280x640 ----------------
(vx, vy, vw, vh), hb = ASSETS['minifactory-horizontal-dark']
lw = 820; s = lw/vw; lh = vh*s
ly = 640/2 - lh/2 - 34
grid = ''.join(f'<circle cx="{x}" cy="{y}" r="1.6" fill="#1E293B"/>' for x in range(40, 1281, 40) for y in range(40, 641, 40))
social = (f'<rect width="1280" height="640" fill="{INK}"/>{grid}'
          f'<g transform="translate({(1280-lw)/2:.2f} {ly:.2f}) scale({s:.5f}) translate({-vx} {-vy})">{hb}</g>'
          + txt('A tiny pluggable software factory', 'jbm400', 34, TEAL_TINT, 640, ly + lh + 44, 'middle'))
social_svg = svg_doc((0, 0, 1280, 640), social, 1280, 640, 'minifactory: A tiny pluggable software factory')
open(os.path.join(SVG_DIR, 'minifactory-social-preview.svg'), 'w').write(social_svg)
cairosvg.svg2png(bytestring=social_svg.encode(), write_to=os.path.join(OUT, 'minifactory-social-preview-1280x640.png'), output_width=1280)

# ---------------- brand sheet 2400x1600 ----------------
W, H = 2400, 1600; M = 80
b = [f'<rect width="{W}" height="{H}" fill="{OFFWHITE}"/>']
b.append(txt('minifactory', 'manrope700', 40, INK, M, 108))
b.append(txt('brand sheet  ·  v1.0', 'jbm400', 24, SLATE, W - M, 106, 'end'))
b.append(f'<rect x="{M}" y="136" width="{W-2*M}" height="2" fill="#E2E8F0"/>')
# hero panels
py, ph = 176, 520; pw = (W - 2*M - 40)/2
b.append(f'<rect x="{M}" y="{py}" width="{pw}" height="{ph}" rx="24" fill="#FFFFFF" stroke="#E2E8F0" stroke-width="2"/>')
b.append(f'<rect x="{M+pw+40}" y="{py}" width="{pw}" height="{ph}" rx="24" fill="{INK}"/>')
for i, a in enumerate(['minifactory-horizontal-light', 'minifactory-horizontal-dark']):
    x0 = M + i*(pw+40); lw = pw - 160
    (vx, vy, vw, vh), _ = ASSETS[a]; lh = vh*lw/vw
    g, _ = place(a, x0 + 80, py + (ph - lh)/2 - 10, lw); b.append(g)
    b.append(txt(['PRIMARY · ON LIGHT', 'PRIMARY · ON DARK'][i], 'jbm500', 20, [SLATE, '#94A3B8'][i], x0 + 40, py + ph - 36))
# variants row
vy0, vh0 = 736, 340
cells = [('minifactory-stacked-light', 'light', 'STACKED'), ('minifactory-stacked-dark', 'dark', 'STACKED'),
         ('minifactory-icon-light', 'light', 'ICON'), ('minifactory-icon-dark', 'dark', 'ICON'),
         ('minifactory-icon-mono-navy', 'light', 'MONO'), ('fav', 'light', 'FAVICON')]
n = len(cells); cw = (W - 2*M - (n-1)*24)/n
for i, (a, mode, lab) in enumerate(cells):
    x0 = M + i*(cw+24)
    if mode == 'light':
        b.append(f'<rect x="{x0:.1f}" y="{vy0}" width="{cw:.1f}" height="{vh0}" rx="20" fill="#FFFFFF" stroke="#E2E8F0" stroke-width="2"/>')
    else:
        b.append(f'<rect x="{x0:.1f}" y="{vy0}" width="{cw:.1f}" height="{vh0}" rx="20" fill="{INK}"/>')
    if a == 'fav':
        # 512-style app icon, 32 grid at 4x, 16 grid at 4x
        items = [(app_icon_elems(320), 320, 112), (fav32_elems(), 32, 64), (fav16_elems(), 16, 40)]
        tot = sum(z for _, _, z in items) + 2*24; xx = x0 + (cw - tot)/2
        for el, vbw, z in items:
            b.append(f'<g transform="translate({xx:.2f} {vy0 + 150 - z/2:.2f}) scale({z/vbw:.5f})">{el}</g>'); xx += z + 24
    else:
        (vx, vy, vw, vh), _ = ASSETS[a]
        lw = cw - 90 if lab != 'STACKED' else cw - 110
        lh = vh*lw/vw
        if lh > 220: lw *= 220/lh; lh = 220
        g, _ = place(a, x0 + (cw - lw)/2, vy0 + 150 - lh/2, lw); b.append(g)
    b.append(txt(lab, 'jbm500', 18, SLATE if mode == 'light' else '#94A3B8', x0 + 28, vy0 + vh0 - 28))
# palette
pal = [('Teal', TEAL, 'Primary · icon, accents'), ('Deep Teal', TEAL_DARK, 'Teal text & links on white'),
       ('Ink Navy', INK, 'Wordmark, text, dark bg'), ('Teal Tint', TEAL_TINT, 'Highlights, tags, fills'),
       ('Off-white', OFFWHITE, 'Light background')]
sy = 1120
b.append(txt('PALETTE', 'jbm500', 20, SLATE, M, sy + 4))
sw = (1400 - 4*20)/5
for i, (nm, hx, role) in enumerate(pal):
    x0 = M + i*(sw+20); y0 = sy + 28
    stroke = ' stroke="#E2E8F0" stroke-width="2"' if hx in (OFFWHITE, TEAL_TINT) else ''
    b.append(f'<rect x="{x0:.1f}" y="{y0}" width="{sw:.1f}" height="320" rx="18" fill="{hx}"{stroke}/>')
    on = OFFWHITE if lum(hx) < 0.2 else INK
    cr_w, cr_n = contrast(hx, '#FFFFFF'), contrast(hx, INK)
    b.append(txt(nm, 'manrope700', 28, on, x0 + 22, y0 + 52))
    b.append(txt(hx, 'jbm500', 24, on, x0 + 22, y0 + 88))
    b.append(txt(f'{cr_w:.2f}:1 vs white', 'jbm400', 17, on, x0 + 22, y0 + 262))
    b.append(txt(f'{cr_n:.2f}:1 vs navy', 'jbm400', 17, on, x0 + 22, y0 + 290))
    b.append(txt(role, 'manrope500', 20, SLATE, x0 + 4, y0 + 356))
# typography
tx0 = M + 1400 + 60; tw = W - M - tx0
b.append(txt('TYPOGRAPHY', 'jbm500', 20, SLATE, tx0, sy + 4))
b.append(f'<rect x="{tx0}" y="{sy+28}" width="{tw}" height="356" rx="18" fill="#FFFFFF" stroke="#E2E8F0" stroke-width="2"/>')
b.append(txt('Manrope SemiBold', 'manrope600', 40, INK, tx0 + 32, sy + 92))
b.append(txt('Wordmark & headings — Aa Bb 0123', 'manrope500', 22, SLATE, tx0 + 32, sy + 130))
b.append(f'<rect x="{tx0+32}" y="{sy+160}" width="{tw-64}" height="2" fill="#E2E8F0"/>')
b.append(txt('JetBrains Mono', 'jbm500', 36, INK, tx0 + 32, sy + 220))
b.append(txt('Code & secondary — CLI, docs, labels', 'manrope500', 22, SLATE, tx0 + 32, sy + 256))
b.append(f'<rect x="{tx0+32}" y="{sy+280}" width="{tw-64}" height="96" rx="10" fill="{INK}"/>')
b.append(txt('$ minifactory run workflow.yaml', 'jbm400', 22, OFFWHITE, tx0 + 56, sy + 320))
b.append(txt('  lint · ok   test · ok   gate:review · passed', 'jbm400', 20, TEAL, tx0 + 56, sy + 354))
b.append(f'<rect x="{M}" y="1530" width="{W-2*M}" height="2" fill="#E2E8F0"/>')
b.append(txt('Wordmark: Manrope SemiBold, outlined  ·  Code: JetBrains Mono  ·  both SIL OFL 1.1  ·  Clear space: keep at least half the icon height around the logo', 'jbm400', 18, SLATE, M, 1568))
sheet_svg = svg_doc((0, 0, W, H), ''.join(b), W, H, 'minifactory brand sheet')
open(os.path.join(SVG_DIR, 'minifactory-brand-sheet.svg'), 'w').write(sheet_svg)
cairosvg.svg2png(bytestring=sheet_svg.encode(), write_to=os.path.join(OUT, 'minifactory-brand-sheet.png'), output_width=W)

# contrast report
pairs = [('Teal #14B8A6 on white', TEAL, '#FFFFFF'), ('Teal #14B8A6 on off-white', TEAL, OFFWHITE),
         ('Deep Teal #0F766E on white', TEAL_DARK, '#FFFFFF'), ('Deep Teal #0F766E on off-white', TEAL_DARK, OFFWHITE),
         ('Ink Navy #0F172A on white', INK, '#FFFFFF'), ('Ink Navy on off-white', INK, OFFWHITE),
         ('Teal #14B8A6 on navy', TEAL, INK), ('Off-white on navy', OFFWHITE, INK), ('Teal Tint on navy', TEAL_TINT, INK),
         ('Navy on Teal', INK, TEAL), ('Deep Teal on Teal Tint', TEAL_DARK, TEAL_TINT), ('Slate #64748B on off-white', SLATE, OFFWHITE)]
for nm, a, c in pairs:
    r = contrast(a, c)
    v = 'AAA' if r >= 7 else 'AA' if r >= 4.5 else 'AA-large/UI' if r >= 3 else 'FAIL'
    print(f'{nm:34s} {r:5.2f}:1  {v}')
