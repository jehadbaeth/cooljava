#!/usr/bin/env python3
"""Render the collection to a static HTML site in _site/ (used for GitHub Pages).

  pip install markdown-it-py mdit-py-plugins
  python3 tools/site.py            # writes _site/
  python3 -m http.server -d _site  # preview at http://localhost:8000

Why not plain Jekyll: Jekyll runs Liquid over every page, and Java code is full of
`{{` (double brace initialization, nested blocks), which Liquid would eat. Rendering
with markdown-it keeps the Markdown exactly as GitHub shows it.
"""
import html
import re
import shutil
from pathlib import Path

from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"
HLJS = "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.11.2"


def slug(text):
    # Same rule GitHub uses for heading ids, so README anchors keep working.
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


md = (
    MarkdownIt("commonmark", {"html": True, "typographer": False})
    .enable("table")
    .enable("strikethrough")
    .use(anchors_plugin, min_level=1, max_level=3, slug_func=slug)
)


def rewrite_links(tokens):
    for tok in tokens:
        if tok.children:
            rewrite_links(tok.children)
        if tok.type == "link_open":
            href = tok.attrGet("href") or ""
            if re.match(r"^[a-z]+:", href) or href.startswith("#"):
                continue
            path, _, frag = href.partition("#")
            if path.endswith("README.md"):
                path = path[: -len("README.md")] + "index.html"
            elif path.endswith(".md"):
                path = path[:-3] + ".html"
            tok.attrSet("href", path + ("#" + frag if frag else ""))


def label_tables(body):
    """Tag tables so small screens can restyle them: index tables become cards,
    other tables with three or more columns stack each row with column labels."""

    def one(m):
        table = m.group(0)
        headers = [re.sub(r"<[^>]+>", "", h).strip() for h in re.findall(r"<th[^>]*>(.*?)</th>", table, re.S)]
        if headers == ["#", "Topic", "Java", "Verdict"]:
            cls = "index"
        elif len(headers) >= 3:
            cls = "stack"
        else:
            return table

        def row(r):
            cells = iter(headers)
            return re.sub(r"<td", lambda _: f'<td data-label="{html.escape(next(cells, ""))}"', r.group(0))

        table = re.sub(r"<tbody>.*?</tbody>", lambda b: re.sub(r"<tr>.*?</tr>", row, b.group(0), flags=re.S), table, flags=re.S)
        return table.replace("<table>", f'<table class="{cls}">', 1)

    return re.sub(r"<table>.*?</table>", one, body, flags=re.S)


def render(text):
    tokens = md.parse(text)
    rewrite_links(tokens)
    return label_tables(md.renderer.render(tokens, md.options, {}))


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="stylesheet" href="{hljs}/styles/github.min.css" media="(prefers-color-scheme: light)">
<link rel="stylesheet" href="{hljs}/styles/github-dark.min.css" media="(prefers-color-scheme: dark)">
<style>
:root {{ --bg:#ffffff; --fg:#1f2328; --muted:#59636e; --border:#d1d9e0; --code:#f6f8fa; --link:#0969da; --accent:#bf3989; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --border:#3d444d; --code:#151b23; --link:#4493f8; --accent:#ff7bb6; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg); font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif; }}
header, main, footer {{ max-width: 920px; margin: 0 auto; padding: 0 16px; }}
header {{ display:flex; justify-content:space-between; align-items:center; gap:12px; padding-top:18px; padding-bottom:12px; border-bottom:1px solid var(--border); }}
header a.brand {{ font-weight:700; font-size:1.1rem; color:var(--fg); text-decoration:none; }}
header a.brand span {{ color:var(--accent); }}
nav.pager {{ display:flex; gap:14px; font-size:.9rem; }}
a {{ color:var(--link); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
h1, h2, h3 {{ line-height:1.25; }}
h1 {{ font-size:2rem; margin-top:1.4rem; }}
h2 {{ border-bottom:1px solid var(--border); padding-bottom:.3rem; margin-top:2rem; }}
blockquote {{ margin:0; padding:.2rem 1rem; color:var(--muted); border-left:4px solid var(--accent); font-size:1.05rem; }}
code {{ font:0.88em ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; background:var(--code); padding:.15em .35em; border-radius:6px; }}
pre {{ background:var(--code); border:1px solid var(--border); border-radius:8px; padding:14px 16px; overflow-x:auto; line-height:1.45; }}
pre code {{ background:none; padding:0; font-size:.85rem; }}
pre code.hljs {{ background:none; padding:0; }}
table {{ border-collapse:collapse; width:100%; display:block; overflow-x:auto; font-size:.95rem; }}
th, td {{ border:1px solid var(--border); padding:6px 12px; vertical-align:top; text-align:left; }}
th {{ background:var(--code); }}
img {{ max-width:100%; }}
main {{ overflow-wrap:break-word; }}
:not(pre) > code, main a {{ overflow-wrap:anywhere; }}
ul, ol {{ padding-left:1.6rem; }}
@media (max-width: 640px) {{
  body {{ font-size:15.5px; }}
  h1 {{ font-size:1.6rem; }}
  h2 {{ font-size:1.3rem; }}
  ul, ol {{ padding-left:1.2rem; }}
  pre {{ padding:10px 12px; margin-left:-4px; margin-right:-4px; }}
  pre code {{ font-size:.78rem; }}
  blockquote {{ padding:.1rem .8rem; font-size:1rem; }}
  header {{ padding-top:12px; padding-bottom:8px; }}
  nav.pager {{ gap:10px; }}
  /* wide tables: one card per row, every cell labelled with its column */
  table.stack, table.stack tbody, table.stack tr, table.stack td {{ display:block; width:100%; }}
  table.stack thead {{ display:none; }}
  table.stack tr {{ border:1px solid var(--border); border-radius:8px; padding:6px 12px; margin:0 0 10px; }}
  table.stack td {{ border:0; padding:4px 0; }}
  table.stack td::before {{ content:attr(data-label); display:block; font-size:.72rem; font-weight:600; letter-spacing:.04em; text-transform:uppercase; color:var(--muted); }}
  /* index tables: number and title on top, version and verdict as pills below */
  table.index, table.index tbody {{ display:block; }}
  table.index thead {{ display:none; }}
  table.index tr {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:6px 8px; border:1px solid var(--border); border-radius:8px; padding:10px 12px; margin:0 0 10px; }}
  table.index td {{ display:block; border:0; padding:0; }}
  table.index td:nth-child(1) {{ font-weight:700; color:var(--muted); font-variant-numeric:tabular-nums; width:2.4rem; }}
  table.index td:nth-child(2) {{ flex:1 1 calc(100% - 3.4rem); min-width:0; }}
  table.index td:nth-child(3) {{ margin-left:2.9rem; }}
  table.index td:nth-child(3), table.index td:nth-child(4) {{ font-size:.82rem; color:var(--muted); background:var(--code); border-radius:999px; padding:1px 10px; }}
}}
footer {{ color:var(--muted); font-size:.85rem; border-top:1px solid var(--border); margin-top:3rem; padding-top:12px; padding-bottom:28px; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
</style>
</head>
<body>
<header><a class="brand" href="{root}index.html">Cool <span>Java</span></a><nav class="pager">{pager}</nav></header>
<main>
{body}
</main>
<footer><span>{footer_left}</span><nav class="pager">{pager}</nav></footer>
<script src="{hljs}/highlight.min.js"></script>
<script>
document.querySelectorAll('pre code').forEach(function (el) {{
  if (/language-(text|output)/.test(el.className)) return;
  hljs.highlightElement(el);
}});
</script>
</body>
</html>
"""


def first_heading(text):
    m = re.search(r"^# (.+)$", text, re.M)
    return m.group(1).strip() if m else "Cool Java"


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    docs = sorted(ROOT.glob("[0-9][0-9]-*/[0-9][0-9][0-9]-*.md"))

    readme = (ROOT / "README.md").read_text()
    (OUT / "index.html").write_text(
        PAGE.format(
            title="Cool Java: 100 tricks, patterns and implementations",
            hljs=HLJS,
            root="",
            pager=f'<a href="{docs[0].relative_to(ROOT).with_suffix(".html").as_posix()}">Start reading</a>',
            body=render(readme),
            footer_left=f"{len(docs)} documents, every example compiled and run",
        )
    )

    for i, path in enumerate(docs):
        text = path.read_text()
        rel = path.relative_to(ROOT)
        links = ['<a href="../index.html">Index</a>']
        if i > 0:
            prev = docs[i - 1].relative_to(ROOT).with_suffix(".html").as_posix()
            links.insert(0, f'<a href="../{prev}">&larr; {docs[i - 1].name[:3]}</a>')
        if i + 1 < len(docs):
            nxt = docs[i + 1].relative_to(ROOT).with_suffix(".html").as_posix()
            links.append(f'<a href="../{nxt}">{docs[i + 1].name[:3]} &rarr;</a>')
        target = OUT / rel.with_suffix(".html")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            PAGE.format(
                title=html.escape(first_heading(text)) + " · Cool Java",
                hljs=HLJS,
                root="../",
                pager=" ".join(links),
                body=render(text),
                footer_left=html.escape(first_heading(text)),
            )
        )
    (OUT / ".nojekyll").write_text("")
    print(f"wrote {len(docs) + 1} pages to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
