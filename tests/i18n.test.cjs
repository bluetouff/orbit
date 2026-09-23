const test=require('node:test');
const assert=require('node:assert/strict');
const {translate}=require('../web/i18n.js');
test('French and English translations preserve literal interpolation values',()=>{
  assert.equal(translate('Add {name}','fr',{name:'<img src=x onerror=alert(1)>'}),'Ajouter <img src=x onerror=alert(1)>');
  assert.equal(translate('{n} coins','fr',{n:50}),'50 cryptos');
  assert.equal(translate('{n} coins','en',{n:50}),'50 coins');
  assert.equal(translate('Signals','fr'),'Signaux');
});
test('unknown keys and languages have deterministic fallbacks without prototype lookup',()=>{
  assert.equal(translate('Untranslated','fr'),'Untranslated');
  assert.equal(translate('Signals','__proto__'),'Signals');
  assert.equal(translate('constructor','fr'),'constructor');
  assert.equal(translate('{missing}','fr',{}),'{missing}');
});
