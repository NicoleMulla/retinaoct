#!/usr/bin/env python3
"""Append a content hash to static asset URLs so browsers fetch new versions.

Pages serves CSS and images with a four-hour cache and no revalidation, so a
deploy is invisible to anyone who has already loaded the page. Stamping the
URL with a hash of the file's contents means the URL changes whenever the file
does, and never otherwise.
"""
import hashlib, re, pathlib

PUB = pathlib.Path("public")
ASSETS = ["styles.css", "hero.webp", "favicon.svg"]

def short_hash(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:8]

def main():
    stamps = {a: short_hash(PUB / a) for a in ASSETS if (PUB / a).exists()}
    for name, h in stamps.items():
        print(f"  {name:<14} {h}")

    for page in PUB.glob("*.html"):
        s = original = page.read_text()
        for name, h in stamps.items():
            # match /name or name, with or without an existing ?v=
            s = re.sub(rf'(["\'])(/?){re.escape(name)}(\?v=[0-9a-f]+)?\1',
                       rf'\g<1>\g<2>{name}?v={h}\g<1>', s)
        if s != original:
            page.write_text(s)
            print(f"  stamped {page.name}")

if __name__ == "__main__":
    main()
