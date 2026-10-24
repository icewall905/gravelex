// Exercise the actual rendering gates with cached observations and a moving clock.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'../web/app.js'),'utf8');
function extract(name) {
 const start=source.indexOf(`function ${name}(`); assert(start>=0);
 let brace=source.indexOf('{',start),depth=1,end=brace+1;
 while(depth && end<source.length) { if(source[end]==='{')depth++; if(source[end]==='}')depth--; end++; }
 return source.slice(start,end);
}
const context={Date,isNum:n=>typeof n==='number'&&Number.isFinite(n),rec:()=>context.record,
 isoOf:d=>d.toISOString().slice(0,10)};
vm.createContext(context); vm.runInContext(extract('stockStrainFresh')+'\n'+extract('readinessNow'),context);
const observed=1700000000, model={score:70,measured_at:observed,age_seconds:1};
assert.equal(context.stockStrainFresh(model,observed+30*3600),true);
assert.equal(context.stockStrainFresh(model,observed+36*3600+1),false);
assert.equal(context.stockStrainFresh(model,observed-1),false);
context.record={today:'2001-01-01',readiness:{formula_version:'readiness-stock-v1',score:77,sleep_based_score:80}};
assert.equal(context.readinessNow().score,null); assert.equal(context.readinessNow().sleep_based_score,null);
context.record.today=new Date().toISOString().slice(0,10); assert.equal(context.readinessNow().score,77);
console.log('Stock estimate cache expiry checks passed');
