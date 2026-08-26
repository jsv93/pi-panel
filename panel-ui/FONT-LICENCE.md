# Bundled font

`outfit-200.woff2`, `outfit-300.woff2`, `outfit-400.woff2`, `outfit-500.woff2`
are the Outfit typeface, by Smartsheet Inc., under the SIL Open Font License
1.1 — <https://openfontlicense.org>. Latin subset, ~6 KB each.

Four static weights, not one variable file. The first attempt bundled a single
woff2 fetched from a weight-range request and declared it
`format("woff2-variations")`; what came back was a *static* instance with no
`fvar` table, so `font-weight: 200` had nothing to interpolate and the clock —
the one place the theme leans hardest on a light weight — silently rendered at
regular. It looked like the wrong typeface because it was the wrong weight.

Bundled rather than linked because a wall panel comes up with the config
server unreachable and often with no internet, and a webfont that fails on
those mornings falls back to a face the Ambient theme's proportions were not
set against. Served to the admin GUI over `/fonts/<name>` from the same files.

Source: <https://fonts.google.com/specimen/Outfit>. Only the Ambient theme
uses them; the default theme is unchanged.
