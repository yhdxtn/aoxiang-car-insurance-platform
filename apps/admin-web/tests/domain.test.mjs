import test from 'node:test';
import assert from 'node:assert/strict';
import {
  menu,
  nextOrderStates,
  policyError,
  money,
  orderAmount,
  orderStateOptions,
} from '../src/domain.js';
test('finance has financial read access but no account administration or channel credential controls', () => {
  const visible = menu.filter((i) => i.roles.includes('FINANCE')).map((i) => i.id);
  assert.ok(visible.includes('finance'));
  assert.ok(visible.includes('points'));
  assert.ok(!visible.includes('users'));
  assert.ok(!visible.includes('taikang'));
  assert.ok(!visible.includes('audit'));
});
test('terminal orders cannot be reopened by the UI', () => {
  assert.deepEqual(nextOrderStates('COMPLETED'), []);
  assert.deepEqual(nextOrderStates('CANCELLED'), []);
  assert.deepEqual(nextOrderStates('PENDING_REVIEW'), ['PROCESSING', 'CANCELLED']);
});
const parent = {
  rate: '5',
  vehicleType: 'CAR',
  effectiveFrom: '2026-01-01',
  effectiveTo: '2026-12-31',
};
const valid = {
  title: '已确认政策',
  content: '规则',
  orgId: 'child',
  rate: '4',
  vehicleType: 'CAR',
  effectiveFrom: '2026-05-01',
  effectiveTo: '2026-06-01',
};
test('child policy cannot exceed parent rate, vehicle type or validity', () => {
  assert.equal(policyError(valid, parent), '');
  assert.match(policyError({ ...valid, rate: '6' }, parent), /超过/);
  assert.match(policyError({ ...valid, vehicleType: 'TRUCK' }, parent), /车辆类型/);
  assert.match(policyError({ ...valid, effectiveTo: '' }, parent), /有效期/);
  assert.match(policyError({ ...valid, effectiveFrom: '2025-12-31' }, parent), /早于/);
});
test('missing and invalid commission rules are not silently treated as zero', () => {
  assert.ok(policyError({ ...valid, rate: '' }, parent));
  assert.ok(policyError({ ...valid, rate: 'garbage' }, parent));
  assert.ok(policyError({ ...valid, rate: '-1' }, parent));
  assert.ok(policyError({ ...valid, rate: '100.01' }, parent));
});
test('money display handles missing quotes explicitly', () => {
  assert.equal(money(undefined), '—');
  assert.equal(money('1256.80'), '1,256.80');
});

test('manual orders never display unconfirmed premiums as zero and agents cannot confirm them', () => {
  assert.equal(money(null), '—');
  assert.equal(orderAmount(null), '待人工核价');
  assert.equal(orderAmount('123.40'), '¥ 123.40');
  const order = { status: 'PROCESSING', quoteId: null, premiumConfirmed: false };
  assert.ok(!orderStateOptions(order, 'AGENT').includes('COMPLETED'));
  assert.ok(orderStateOptions(order, 'SERVICE').includes('PROCESSING'));
  assert.deepEqual(orderStateOptions({ ...order, status: 'COMPLETED' }, 'SERVICE'), []);
});
