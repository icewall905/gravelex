# Pebble Health logo

`brand.svg` is the original scalable mark: a soft pebble silhouette with an inset
pulse and a violet signal node. The header and sign-in page use it directly.

Regenerate the PNG icons from the repository root with:

```sh
python3 health-hub/scripts/build-icons.py
```

The development-only renderer is KDE's `ksvgtopng5` or `ksvgtopng` (Qt SVG).
Production serves the committed assets and needs no SVG rendering dependency.
The script also regenerates `brand-app.svg` and `brand-maskable.svg` from the master.
Regular icons have a rounded navy backing; maskable icons have an opaque square
backing and inset artwork for operating-system masks. Apple touch is 180 px,
favicon is 32 px, and the PWA variants are 192 and 512 px.
