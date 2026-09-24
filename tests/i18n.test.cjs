const test=require('node:test');
const assert=require('node:assert/strict');
const {translate}=require('../web/i18n.js');
test('French and English translations preserve literal interpolation values',()=>{
  assert.equal(translate('Add {name}','fr',{name:'<img src=x onerror=alert(1)>'}),'Ajouter <img src=x onerror=alert(1)>');
  assert.equal(translate('{n} assets','fr',{n:50}),'50 actifs');
  assert.equal(translate('{n} assets','en',{n:50}),'50 assets');
  assert.equal(translate('Signals','fr'),'Signaux');
  assert.equal(translate('{n} asset','fr',{n:1}),'1 actif');
  assert.equal(translate('Asset performance heatmap','fr'),'Carte des performances des actifs');
});
test('unknown keys and languages have deterministic fallbacks without prototype lookup',()=>{
  assert.equal(translate('Untranslated','fr'),'Untranslated');
  assert.equal(translate('Signals','__proto__'),'Signals');
  assert.equal(translate('constructor','fr'),'constructor');
  assert.equal(translate('{missing}','fr',{}),'{missing}');
});
