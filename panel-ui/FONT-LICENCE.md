# Bundled font

`outfit.woff2` is the Outfit variable font, by Smartsheet Inc., under the
SIL Open Font License 1.1 — <https://openfontlicense.org>.

It is bundled rather than linked from a font host because a wall panel has to
come up with the config server unreachable and often with no internet at all.
A webfont that fails on those mornings falls back to a face the Ambient theme
was not drawn for, which is a worse failure than it sounds: the theme's
proportions are set against Outfit's.

Source: <https://fonts.google.com/specimen/Outfit> (variable, weights 200–500,
14.5 KB). Only the Ambient theme uses it; the default theme is unchanged.
