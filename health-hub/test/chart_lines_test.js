const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname, '../web/app.js'), 'utf8');
const fragment = source.slice(source.indexOf('function seriesPaths('), source.indexOf('/* Line chart with gaps'));
const context = {
  isNum: Number.isFinite,
  s: (tag, attrs) => ({ tag, attrs }),
};
vm.createContext(context);
vm.runInContext(fragment, context);

const paths = context.seriesPaths(
  [{ v: 10 }, { v: 15 }, { v: null }, { v: 25 }, { v: 28, breakBefore: true }, { v: 30 }],
  'v', i => i * 10, value => value,
);
assert.equal(paths.line, 'M0.0 10.0L10.0 15.0M30.0 25.0M40.0 28.0L50.0 30.0');
assert.equal(paths.gaps, 'M10.0 15.0L30.0 25.0');

const snapshots = [{ v: 60, snapshot: true }, { v: 85 }, { v: 80 }];
const kids = [];
context.drawSeries(kids, context.seriesPaths(snapshots, 'v', i => i, Number, (a, b) => a.snapshot || b.snapshot));
assert.equal(kids[0].attrs.style, 'stroke-dasharray:2 5;stroke-opacity:.5');
assert.equal(kids[0].attrs.d, 'M0.0 60.0L1.0 85.0');
assert.equal(kids[1].attrs.d, 'M0.0 60.0M1.0 85.0L2.0 80.0');
