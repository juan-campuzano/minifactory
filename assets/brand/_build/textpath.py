import uharfbuzz as hb
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.pens.boundsPen import BoundsPen
import os
D = os.path.join(os.path.dirname(__file__), '..', 'fonts-src')
FONTS = {
 'manrope600': 'manrope-latin-600-normal.woff',
 'manrope700': 'manrope-latin-700-normal.woff',
 'manrope500': 'manrope-latin-500-normal.woff',
 'jbm400': 'jetbrains-mono-latin-400-normal.woff',
 'jbm500': 'jetbrains-mono-latin-500-normal.woff',
}
_cache = {}
def _load(key):
    if key not in _cache:
        p = os.path.join(D, FONTS[key])
        tt = TTFont(p)
        # harfbuzz needs sfnt; re-serialize as plain ttf/otf bytes
        tt.flavor = None
        import io
        b = io.BytesIO(); tt.save(b); data = b.getvalue()
        face = hb.Face(data); font = hb.Font(face)
        tt2 = TTFont(io.BytesIO(data))
        _cache[key] = (font, tt2, tt2.getGlyphSet(), tt2['head'].unitsPerEm, tt2.getGlyphOrder())
    return _cache[key]

def text_path(text, key, size, tracking=0.0, features=None):
    """Return (d, advance_width, ink_bbox) for text with baseline at y=0, x starting at 0.
    tracking in em units (e.g. -0.01)."""
    font, tt, gs, upem, order = _load(key)
    buf = hb.Buffer(); buf.add_str(text); buf.guess_segment_properties()
    hb.shape(font, buf, features or {})
    s = size / upem
    x = 0.0
    pen = SVGPathPen(gs)
    bp = BoundsPen(gs)
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        name = order[info.codepoint]
        t = (s, 0, 0, -s, (x + pos.x_offset) * s, -pos.y_offset * s)
        gs[name].draw(TransformPen(pen, t))
        gs[name].draw(TransformPen(bp, t))
        x += pos.x_advance + tracking * upem
    adv = (x - tracking * upem) * s
    return pen.getCommands(), adv, bp.bounds

def metrics(key, size):
    font, tt, gs, upem, order = _load(key)
    s = size / upem
    return dict(xh=tt['OS/2'].sxHeight * s, cap=tt['OS/2'].sCapHeight * s)
