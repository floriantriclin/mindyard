# mindyard.dev

The landing page of mindyard: one static HTML file, no build step, no framework.
Styles and the copy-button script are inlined so the page renders in one request.

```text
index.html             the page (SEO meta, Open Graph, JSON-LD, waitlist form)
thanks.html, privacy.html, legal.html
waitlist/waitlist.py   the form endpoint, standard library only (tests in tests/)
404.html               not-found page, noindex
robots.txt, sitemap.xml
icon.svg               copy of src/mindyard/static/icon.svg
favicon.ico, apple-touch-icon.png, og.png   generated, see below
tools/og.html          source of og.png (1200x630)
tools/build_assets.py  regenerates the three generated images
```

Preview locally:

```bash
python3 -m http.server -d site 8000
```

Regenerate the images after changing `icon.svg` or `tools/og.html`:

```bash
uv run --with playwright python site/tools/build_assets.py
```

The session shown on the page was played against the demo vault
(`mindyard init --demo`); its outputs are verbatim. Replay it if the tools or their
messages change.

The waitlist form posts to `/api/waitlist`; run the endpoint locally with
`python3 site/waitlist/waitlist.py serve --db /tmp/w.sqlite` and count sign-ups with
`python3 site/waitlist/waitlist.py count --db /tmp/w.sqlite`. It keeps the email, the
optional price bracket, the date and the consent version: no IP address, no cookie.
If the form or its retention changes, update `privacy.html` and `CONSENT_VERSION`.

`site/` is excluded from the source distribution. The deployment itself is not part
of this repository.
