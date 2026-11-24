// Tests for the browser app's rules engine. Run with: node --test
'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { loadModel } = require('./model_bridge.js');

const M = loadModel();
const AS_OF = '2026-11-24';
// The model runs in its own VM context, so compare plain copies of its arrays.
const plain = function (x) { return JSON.parse(JSON.stringify(x)); };
const ids = function (res) { return plain(res.obligations.map(function (o) { return o.id; })); };
const ob = function (res, id) { return res.obligations.filter(function (o) { return o.id === id; })[0]; };

test('out of scope for each exclusion', function () {
  assert.equal(M.classify({ eu: false }, AS_OF).tier, 'outOfScope');
  assert.equal(M.classify({ excluded: 'military', annex3: 'employment' }, AS_OF).tier, 'outOfScope');
  assert.equal(M.classify({ excluded: 'research' }, AS_OF).tier, 'outOfScope');
  assert.equal(M.classify({ excluded: 'personal', role: 'deployer' }, AS_OF).tier, 'outOfScope');
  assert.notEqual(M.classify({ excluded: 'personal', role: 'provider' }, AS_OF).tier, 'outOfScope', 'providers are still covered');
  assert.equal(M.classify({ eu: false }, AS_OF).obligations.length, 0);
});

test('banned practices stop the analysis, with the right dates', function () {
  const r = M.classify({ prohibited: ['emotionWork', 'csam'], annex3: 'employment' }, AS_OF);
  assert.equal(r.tier, 'prohibited');
  assert.deepEqual(ids(r), ['ban_emotionWork', 'literacy', 'ban_csam']);
  assert.equal(ob(r, 'ban_emotionWork').date, '2025-02-02');
  assert.equal(ob(r, 'ban_emotionWork').status, 'applies');
  assert.equal(ob(r, 'ban_csam').date, '2026-12-02', 'added by the Digital Omnibus');
  assert.equal(ob(r, 'ban_csam').status, 'upcoming');
  assert.equal(ob(r, 'ban_csam').originalDate, null);
  assert.equal(r.penalty.key, 'prohibited');
});

test('Annex III: high-risk unless an exemption applies without profiling', function () {
  const hr = M.classify({ role: 'provider', annex3: 'employment' }, AS_OF);
  assert.equal(hr.tier, 'highRisk');
  assert.equal(hr.route, 'annex3');
  assert.equal(ob(hr, 'p_rms').date, '2027-12-02');
  assert.equal(ob(hr, 'p_rms').originalDate, '2026-08-02');
  assert.ok(ids(hr).indexOf('p_register') >= 0);
  const exempt = M.classify({ role: 'provider', annex3: 'employment', derogation: 'improve' }, AS_OF);
  assert.equal(exempt.tier, 'exempt63');
  assert.deepEqual(ids(exempt), ['literacy', 'e_document', 'e_register']);
  assert.equal(ob(exempt, 'e_register').date, '2027-12-02');
  const profiled = M.classify({ role: 'provider', annex3: 'employment', derogation: 'improve', profiling: true }, AS_OF);
  assert.equal(profiled.tier, 'highRisk', 'profiling rules out the exemption');
});

test('Annex I products follow the later date; Annex III wins when both apply', function () {
  const product = M.classify({ role: 'provider', annex1: true }, AS_OF);
  assert.equal(product.route, 'annex1');
  assert.equal(ob(product, 'p_conformity').date, '2028-08-02');
  assert.equal(ids(product).indexOf('p_register'), -1, 'EU database registration is for Annex III systems');
  const both = M.classify({ role: 'provider', annex1: true, annex3: 'biometrics' }, AS_OF);
  assert.equal(both.route, 'annex3');
  assert.equal(ob(both, 'p_rms').date, '2027-12-02');
});

test('deployers who rebrand or change a high-risk system take on provider duties', function () {
  const direct = M.classify({ role: 'deployer', annex3: 'credit' }, AS_OF);
  assert.deepEqual(plain(direct.roles), ['deployer']);
  assert.equal(ids(direct).indexOf('p_rms'), -1);
  const takeover = M.classify({ role: 'deployer', annex3: 'credit', takeover: true }, AS_OF);
  assert.deepEqual(plain(takeover.roles), ['provider', 'deployer']);
  assert.ok(ids(takeover).indexOf('p_rms') >= 0 && ids(takeover).indexOf('d_logs') >= 0);
  assert.deepEqual(plain(M.classify({ role: 'deployer', takeover: true }, AS_OF).roles), ['deployer'], 'only matters for high-risk systems');
});

test('fundamental rights impact assessments go to the right deployers', function () {
  const fria = function (a) { return ids(M.classify(Object.assign({ role: 'deployer' }, a), AS_OF)).indexOf('d_fria') >= 0; };
  assert.equal(fria({ annex3: 'publicBenefits', deployerType: 'publicAuthority' }), true);
  assert.equal(fria({ annex3: 'education', deployerType: 'publicService' }), true);
  assert.equal(fria({ annex3: 'credit' }), true, 'credit scoring, even for a private deployer');
  assert.equal(fria({ annex3: 'insurance' }), true);
  assert.equal(fria({ annex3: 'employment' }), false);
  assert.equal(fria({ annex3: 'infrastructure', deployerType: 'publicAuthority' }), false, 'critical infrastructure is carved out');
  assert.equal(fria({ annex3: 'employment', derogation: 'procedural' }), false, 'not for exempt systems');
  const pa = M.classify({ role: 'deployer', annex3: 'publicBenefits', deployerType: 'publicAuthority' }, AS_OF);
  assert.ok(ids(pa).indexOf('d_register') >= 0);
});

test('transparency duties follow the role, and existing generators get until December 2026', function () {
  const p = M.classify({ role: 'provider', interacts: true, generates: true }, AS_OF);
  assert.equal(p.tier, 'transparency');
  assert.equal(ob(p, 't_mark').date, '2026-08-02');
  assert.equal(ob(p, 't_mark').status, 'applies');
  const legacy = M.classify({ role: 'provider', generates: true, generatedBefore: true }, AS_OF);
  assert.equal(ob(legacy, 't_mark').date, '2026-12-02');
  assert.equal(ob(legacy, 't_mark').daysUntil, 8);
  const d = M.classify({ role: 'deployer', interacts: true, generates: true }, AS_OF);
  assert.equal(d.tier, 'minimal', 'provider duties do not fall on a deployer');
  const dd = M.classify({ role: 'deployer', deepfake: true, emotionBiocat: true }, AS_OF);
  assert.deepEqual(ids(dd), ['literacy', 't_emotion', 't_deepfake']);
});

test('general-purpose AI models', function () {
  const open = M.classify({ role: 'provider', gpai: 'gpai', gpaiOpen: true }, AS_OF);
  assert.equal(open.tier, 'gpai');
  assert.deepEqual(ids(open), ['literacy', 'g_copyright', 'g_summary']);
  const systemic = M.classify({ role: 'provider', gpai: 'systemic', gpaiOpen: true, gpaiBefore: true }, AS_OF);
  assert.equal(systemic.tier, 'gpaiSystemic');
  assert.ok(ids(systemic).indexOf('g_docs') >= 0, 'open source does not exempt systemic-risk models');
  assert.equal(ob(systemic, 'g_systemic').date, '2027-08-02');
  assert.equal(systemic.penalty.key, 'gpai');
  assert.equal(M.classify({ role: 'deployer', gpai: 'gpai' }, AS_OF).tier, 'minimal');
});

test('fines: the higher of the two amounts, or the lower for SMEs', function () {
  const big = M.classify({ prohibited: ['socialScoring'], turnover: 1000 }, AS_OF).penalty;
  assert.equal(big.max, 70000000);
  const small = M.classify({ prohibited: ['socialScoring'], turnover: 20, sme: true }, AS_OF).penalty;
  assert.equal(small.max, 1400000);
  const hr = M.classify({ annex3: 'employment', turnover: 100 }, AS_OF).penalty;
  assert.equal(hr.max, 15000000);
  assert.equal(M.classify({}, AS_OF).penalty, null);
  assert.equal(M.classify({ role: 'provider', gpai: 'gpai', sme: true, turnover: 1 }, AS_OF).penalty.max, 15000000, 'no SME rule for model providers');
});

test('dates, statuses and defaults', function () {
  assert.equal(M.daysBetween('2026-11-24', '2027-12-02'), 373);
  assert.equal(M.longDate('2027-12-02'), '2 December 2027');
  assert.equal(M.validIso('2026-02-30'), false);
  assert.equal(M.validIso('2026-2-3'), false);
  assert.equal(M.validIso('2028-02-29'), true);
  assert.equal(M.classify({}, 'nonsense').asOf, M.RULES.checked);
  const later = M.classify({ annex3: 'employment' }, '2028-01-01');
  assert.ok(later.obligations.every(function (o) { return o.status === 'applies'; }));
  assert.equal(later.nextDeadline, null);
  assert.equal(M.classify({ annex3: 'employment' }, '2027-12-02').obligations.filter(function (o) { return o.status === 'upcoming'; }).length, 0, 'applies on the day itself');
});

test('every combination of answers gives a coherent result', function () {
  const roles = ['provider', 'deployer', 'both'];
  const areas = [''].concat(M.RULES.annex3.map(function (x) { return x.id; }));
  let n = 0;
  roles.forEach(function (role) {
    areas.forEach(function (annex3) {
      [true, false].forEach(function (annex1) {
        ['', 'procedural'].forEach(function (derogation) {
          [true, false].forEach(function (profiling) {
            ['none', 'gpai', 'systemic'].forEach(function (gpai) {
              const r = M.classify({ role, annex3, annex1, derogation, profiling, gpai, interacts: true, deepfake: true, deployerType: 'publicService' }, AS_OF);
              n++;
              assert.ok(M.TIERS[r.tier], r.tier);
              assert.equal(r.tags.indexOf(r.tier), 0, 'the tier is the most serious tag');
              r.obligations.forEach(function (o) {
                assert.ok(M.validIso(o.date), JSON.stringify(o));
                assert.ok(o.role === 'both' || r.roles.indexOf(o.role) >= 0);
              });
              assert.equal(new Set(ids(r)).size, r.obligations.length, 'no duty listed twice');
              assert.ok(!(r.highRisk && r.exempt));
            });
          });
        });
      });
    });
  });
  assert.equal(n, 3 * 12 * 2 * 2 * 2 * 3);
});
