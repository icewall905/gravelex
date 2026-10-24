#!/usr/bin/env python3
"""Render the original SVG brand into PH icons with KDE's Qt SVG renderer.

Development only: install ksvg's ksvgtopng5/ksvgtopng executable. No runtime dependency.
"""
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

ICONS = Path(__file__).resolve().parents[1] / 'web' / 'icons'
renderer = shutil.which('ksvgtopng5') or shutil.which('ksvgtopng')
if not renderer:
    raise SystemExit('Install ksvgtopng5 or ksvgtopng to render the SVG icon sources.')
source = (ICONS / 'brand.svg').read_text()
root = ET.fromstring(source)
ns = '{http://www.w3.org/2000/svg}'
body = ''.join(ET.tostring(node, encoding='unicode') for node in root if node.tag not in (ns+'title', ns+'desc'))

def app_source(scale, maskable=False):
    offset = 64 * (1-scale)
    radius = 0 if maskable else 28
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
            f'<rect width="128" height="128" rx="{radius}" fill="#101827"/>'
            f'<g transform="translate({offset} {offset}) scale({scale})">{body}</g></svg>')

env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
for filename, scale, outputs in (
    ('brand-app.svg', .82, [('icon-192.png',192),('icon-512.png',512),('apple-touch-icon.png',180)]),
    ('brand-maskable.svg', .72, [('maskable-192.png',192),('maskable-512.png',512)]),
):
    svg = ICONS / filename
    svg.write_text(app_source(scale, maskable='maskable' in filename))
    for name, size in outputs:
        subprocess.run([renderer,str(size),str(size),str(svg),str(ICONS/name)],env=env,check=True)
subprocess.run([renderer,'32','32',str(ICONS/'brand.svg'),str(ICONS/'favicon-32.png')],env=env,check=True)
print('Rendered header, favicon, Apple touch and regular/maskable PWA icons from brand.svg.')
