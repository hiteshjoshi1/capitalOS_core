// #368: move App.css rules that only one importing file uses into that file's own CSS, keeping the
// cascade: a rule moves only if no rule left in App.css after it targets the same elements and
// sets the same property (moved rules load after App.css). Usage: node scripts/split-app-css.mjs web [--apply] (dry run without --apply)
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const webDir = path.resolve(process.argv[2]);
const apply = process.argv.includes("--apply");
const require = createRequire(path.join(webDir, "package.json"));
const postcss = require("postcss");
const src = path.join(webDir, "src");
const appCssPath = path.join(src, "App.css");
const root = postcss.parse(fs.readFileSync(appCssPath, "utf8"));

// Files that import App.css directly: the only possible owners (their CSS loads after App.css).
const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) =>
  e.isDirectory() ? (e.name === "__tests__" ? [] : walk(path.join(d, e.name))) : [path.join(d, e.name)]);
const codeFiles = walk(src).filter((f) => /\.(tsx?|jsx?)$/.test(f) && !/\.test\./.test(f));
const text = Object.fromEntries(codeFiles.map((f) => [f, fs.readFileSync(f, "utf8")]));
const importsApp = new Set(codeFiles.filter((f) => /import\s+["'](\.\.?\/)+App\.css["']/.test(text[f])));

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const usageCache = new Map();
function usedIn(cls) {
  if (usageCache.has(cls)) return usageCache.get(cls);
  const re = new RegExp(`(^|[^\\w-])${esc(cls)}([^\\w-]|$)`);
  let files = codeFiles.filter((f) => re.test(text[f]));
  if (files.length === 0 && cls.includes("--")) {
    // BEM modifier built at runtime (`base--${x}`): owned like its base, if the base is written `base--`.
    const base = cls.slice(0, cls.indexOf("--"));
    const reBase = new RegExp(`(^|[^\\w-])${esc(base)}--`);
    files = codeFiles.filter((f) => reBase.test(text[f]));
  }
  usageCache.set(cls, files);
  return files;
}

// Units: each rule at top level or directly inside a top-level @media, with its leading comments.
const units = [];
let pendingComments = [];
function addUnit(node, media) {
  units.push({ node, media, comments: pendingComments, index: units.length });
  pendingComments = [];
}
root.each((node) => {
  if (node.type === "comment") { pendingComments.push(node); return; }
  if (node.type === "rule") return addUnit(node, null);
  if (node.type === "atrule" && node.name === "media") {
    const before = pendingComments; pendingComments = [];
    node.each((child) => {
      if (child.type === "comment") { pendingComments.push(child); return; }
      if (child.type === "rule") addUnit(child, node); else pendingComments = [];
    });
    units.push({ marker: true, node, comments: before, index: units.length }); // the @media shell itself stays
    pendingComments = [];
    return;
  }
  pendingComments = [];
  units.push({ node, media: null, keep: true, comments: [], index: units.length });
});

const classesOf = (sel) => [...sel.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)].map((m) => m[1]);
// The last compound of each selector: what it actually styles.
const lastCompounds = (rule) => rule.selectors.map((s) => s.trim().split(/\s*[\s>+~]\s*/).pop() ?? "");
const tokens = (compound) => {
  const t = new Set(classesOf(compound).map((c) => "." + c));
  const el = compound.match(/^[a-zA-Z][\w-]*/); if (el) t.add(el[0]);
  if (t.size === 0) t.add("*");
  return t;
};
const props = (rule) => new Set(rule.nodes.filter((n) => n.type === "decl").map((d) => d.prop));

for (const u of units) {
  if (u.marker || u.keep) continue;
  const classes = classesOf(u.node.selector);
  if (classes.length === 0) { u.keep = true; continue; }
  let owner = null;
  for (const c of classes) {
    const files = usedIn(c);
    if (files.length !== 1 || (owner && owner !== files[0])) { owner = null; break; }
    owner = files[0];
  }
  if (!owner || !importsApp.has(owner)) { u.keep = true; continue; }
  u.owner = owner;
  u.tok = lastCompounds(u.node).map(tokens);
  u.props = props(u.node);
}

// Fixpoint: a candidate stays if a later unit that stays in App.css could override it.
let changed = true;
while (changed) {
  changed = false;
  for (const u of units) {
    if (!u.owner) continue;
    for (const v of units.slice(u.index + 1)) {
      if (v.marker || v.owner === u.owner) continue;
      if (v.owner) continue; // moves elsewhere: its elements belong to another file
      if (v.node.type !== "rule") continue;
      const vt = lastCompounds(v.node).map(tokens);
      const overlap = u.tok.some((a) => vt.some((b) => [...a].some((x) => b.has(x) || b.has("*")) || a.has("*")));
      if (!overlap) continue;
      const vp = props(v.node);
      if ([...u.props].some((p) => vp.has(p) || vp.has("all"))) {
        u.owner = null; u.keep = true; changed = true; break;
      }
    }
  }
}

const moved = units.filter((u) => u.owner);
const byOwner = new Map();
for (const u of moved) { if (!byOwner.has(u.owner)) byOwner.set(u.owner, []); byOwner.get(u.owner).push(u); }
const before = fs.readFileSync(appCssPath, "utf8").split("\n").length;
console.log(`App.css units: ${units.filter((u) => !u.marker).length}, movable: ${moved.length}`);
for (const [owner, list] of byOwner) console.log(`  ${path.relative(src, owner)}: ${list.length}`);
if (!apply) process.exit(0);

for (const [owner, list] of byOwner) {
  const out = postcss.root();
  let media = null, mediaClone = null;
  for (const u of list) {
    if (u.media) {
      if (media !== u.media) { media = u.media; mediaClone = u.media.clone({ nodes: [] }); out.append(mediaClone); }
      for (const c of u.comments) mediaClone.append(c.clone());
      mediaClone.append(u.node.clone());
    } else {
      media = null; mediaClone = null;
      for (const c of u.comments) out.append(c.clone());
      out.append(u.node.clone());
    }
  }
  const cssPath = owner.replace(/\.(tsx?|jsx?)$/, ".css");
  const header = `/* Moved from App.css (#368): rules only ${path.basename(owner)} uses. */\n`;
  const body = out.toString().trim() + "\n";
  if (fs.existsSync(cssPath)) {
    // Before the file's own rules: these came from App.css, which loads first.
    fs.writeFileSync(cssPath, header + body + "\n" + fs.readFileSync(cssPath, "utf8"));
  } else {
    fs.writeFileSync(cssPath, header + body);
  }
  const imp = `import "./${path.basename(cssPath)}";`;
  let code = text[owner];
  if (!code.includes(imp)) {
    code = code.replace(/(import\s+["'](\.\.?\/)+App\.css["'];?\n)/, `$1${imp}\n`);
    fs.writeFileSync(owner, code);
  }
}
for (const u of moved) { for (const c of u.comments) c.remove(); u.node.remove(); }
root.walkAtRules("media", (m) => { if (!m.nodes || m.nodes.filter((n) => n.type !== "comment").length === 0) m.remove(); });
fs.writeFileSync(appCssPath, root.toString().replace(/\n{3,}/g, "\n\n"));
const after = fs.readFileSync(appCssPath, "utf8").split("\n").length;
console.log(`App.css lines: ${before} -> ${after}`);
