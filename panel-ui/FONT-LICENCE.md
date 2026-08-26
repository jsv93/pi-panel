# Bundled font

`outfit-200.woff2` … `outfit-500.woff2` are the Outfit typeface, by Smartsheet
Inc., under the SIL Open Font License 1.1 — <https://openfontlicense.org>.

## Take the `/* latin */` block, not the first one

Google's `css2` endpoint returns several `@font-face` blocks per weight, one
per unicode subset, and **latin is not the first**. Taking the first URL gets
`latin-ext`, whose range is `U+0100-02BA, …` — no digits, no basic Latin
letters. The face loads, `document.fonts.check()` says it is available, every
weight registers as `loaded`, and not one glyph on the panel renders in it.
It fails as "the font looks wrong" with nothing anywhere reporting an error.

The latin blocks are `U+0000-00FF, …` and about 14 KB; a latin-ext subset is
about 6 KB. If these files are ever refreshed, take the URL that follows the
`/* latin */` comment and check the size.

## Four static weights, not one variable file

An earlier attempt bundled one file from a weight-*range* request and declared
it `format("woff2-variations")`. What came back was a static instance with no
`fvar` table, so `font-weight: 200` had nothing to interpolate and rendered at
regular.

## Bundled, not linked

A wall panel comes up with the config server unreachable and often with no
internet; a webfont that fails on those mornings falls back to a face this
theme's proportions were not set against. Served to the admin GUI over
`/fonts/<name>` from the same files. Only the Ambient theme uses them.

Source: <https://fonts.google.com/specimen/Outfit>.
