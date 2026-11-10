#!/bin/bash
# Cortex Control Tower — build the frontend to ONE self-contained index.html (config.js stays the first script).
set -e
cd "$(dirname "$0")"
echo "1/4 typecheck"; ./node_modules/.bin/tsc --noEmit
echo "2/4 vite build"; rm -rf dist; ./node_modules/.bin/vite build >/tmp/vite.log 2>&1 || { tail -30 /tmp/vite.log; exit 1; }
echo "3/4 inline js + css + fonts"
node - <<'NODE'
const fs = require('fs'), path = require('path');
const dist = 'dist';
let css = fs.readFileSync(path.join(dist, 'app.css'), 'utf8');
css = css.replace(/url\(([^)]+\.(woff2?|ttf|otf))\)/g, (m, fp) => {
  const clean = fp.replace(/['"]/g, '').replace(/^\.\//, '');
  const abs = path.join(dist, clean);
  if (!fs.existsSync(abs)) return m;
  const ext = path.extname(clean).slice(1);
  return `url(data:font/${ext};base64,${fs.readFileSync(abs).toString('base64')})`;
});
const js = fs.readFileSync(path.join(dist, 'app.js'), 'utf8').replace(/<\/script/gi, '<\\/script');
const html = `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
    <meta name="theme-color" content="#ffffff" />
    <meta name="color-scheme" content="light" />
    <meta name="apple-mobile-web-app-capable" content="yes" />
    <title>Cortex Tower</title>
    <script src="./config.js"></script>
    <style>${css}</style>
  </head>
  <body>
    <div id="root"></div>
    <script type="module">${js}</script>
  </body>
</html>`;
fs.writeFileSync('bundle.html', html);
console.log('   size', fs.statSync('bundle.html').size);
NODE
echo "4/4 copy to artifact"
cp bundle.html ../index.html
rm -rf dist bundle.html
echo "✅ built $(stat -c%s ../index.html) bytes → ../index.html"
