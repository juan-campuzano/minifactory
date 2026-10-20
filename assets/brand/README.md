# minifactory logo kit

Hand-authored geometric SVG. All text is outlined to paths, so the files need no fonts.

## Files
- `svg/` and `png/` (transparent PNGs, 2048 px wide): horizontal, stacked and icon, each in `-light` (for white backgrounds) and `-dark` (for navy backgrounds). Also `icon-mono-navy` and `icon-mono-white`.
- `favicon/`: `favicon.ico` (16/32/48), `favicon-16/32/48/180/512.png`, `apple-touch-icon-180.png` (opaque), `favicon.svg` (32 grid), `favicon-16.svg`, `app-icon.svg`.
- `minifactory-social-preview-1280x640.png`: GitHub social preview.
- `minifactory-brand-sheet.png` (2400×1600).
- `fonts-src/`: the font files used, with their OFL licenses. `_build/`: the generator (`python3 _build/build.py`).

## Icon geometry (256×156 units)
- Frame (guardrails): 8u stroke, rx 28.
- Steps: 36u squares (rx 8) and a 64u middle square (rx 12), joined by 8u connectors.
- Plugin: the right connector ends in a 9u-radius plug. The plug sits in a socket cut into the middle square, with a constant 4u clearance.
- Favicons are separate pixel-snapped drawings on 16 px and 32 px grids, placed on a navy tile.

## Palette
| Name | Hex | Role |
|---|---|---|
| Teal | #14B8A6 | Primary. Icon, accents, teal on navy |
| Deep Teal | #0F766E | Teal text and links on white |
| Ink Navy | #0F172A | Wordmark, body text, dark backgrounds |
| Teal Tint | #CCFBF1 | Highlights, tags, light fills, tagline on navy |
| Off-white | #F8FAFC | Light page background |
| (Slate) | #64748B | Muted labels (brand sheet only) |

## Fonts
- Wordmark and headings: Manrope SemiBold 600, tracking -1%. SIL OFL 1.1.
- Code and secondary: JetBrains Mono 400/500. SIL OFL 1.1.

## Contrast (WCAG 2.x)
See CONTRAST.txt. #14B8A6 on white is 2.49:1, so do not use it for text on white; use #0F766E (5.47:1 AA).
Logos are exempt from WCAG contrast rules. The teal icon on white is decorative brand use.

## HTML
```html
<link rel="icon" href="/favicon.ico" sizes="48x48">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon-180.png">
```
