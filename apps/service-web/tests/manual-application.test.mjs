import test from 'node:test';
import assert from 'node:assert/strict';
import { canCreateManualApplication } from '../src/domain.js';
const service = { id: 'assigned-service', role: 'SERVICE' };
const car = {
  id: 's',
  vehicleType: 'CAR',
  status: 'ACTIVE',
  assignedTo: service.id,
  quotes: [{ status: 'MANUAL_REQUIRED' }],
};
test('claimed car sessions with failed or manual quotes can register an internal application', () => {
  assert.equal(canCreateManualApplication(car, service), true);
  assert.equal(
    canCreateManualApplication({ ...car, quotes: [{ status: 'FAILED' }] }, service),
    true,
  );
});
test('unknown outcomes allow an internal application without replaying an external quote', () => {
  assert.equal(
    canCreateManualApplication({ ...car, quotes: [{ status: 'OUTCOME_UNKNOWN' }] }, service),
    true,
  );
});
test('processing quotes block internal applications for every vehicle type and role', () => {
  for (const vehicleType of ['CAR', 'TRUCK', 'MOTORCYCLE']) {
    const session = {
      ...car,
      vehicleType,
      quotes: [{ status: 'FAILED' }, { status: 'PROCESSING' }],
    };
    assert.equal(canCreateManualApplication(session, service), false);
    assert.equal(canCreateManualApplication(session, { id: 'admin', role: 'ADMIN' }), false);
  }
});
test('unclaimed, differently assigned, closed or already submitted sessions are not editable by service staff', () => {
  assert.equal(
    canCreateManualApplication({ ...car, status: 'WAITING', assignedTo: null }, service),
    false,
  );
  assert.equal(canCreateManualApplication({ ...car, assignedTo: 'another' }, service), false);
  assert.equal(canCreateManualApplication({ ...car, status: 'CLOSED' }, service), false);
  assert.equal(canCreateManualApplication({ ...car, orderId: 'existing' }, service), false);
  assert.equal(canCreateManualApplication(car, { id: service.id, role: 'CUSTOMER' }), false);
});
test('administrators may register a waiting session but BOT sessions need a prior handoff', () => {
  const admin = { id: 'admin', role: 'ADMIN' };
  assert.equal(
    canCreateManualApplication({ ...car, status: 'WAITING', assignedTo: null }, admin),
    true,
  );
  assert.equal(canCreateManualApplication({ ...car, status: 'BOT' }, admin), false);
});
