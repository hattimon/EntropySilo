import test from 'node:test';
import assert from 'node:assert/strict';
import { FULL_DECK, generateFromCards } from '../apps/card-entropy.js';

test('two independent 25-card draws produce a 256-bit, 24-word mnemonic', () => {
  const result = generateFromCards({ deck1: [...FULL_DECK].slice(0, 25), deck2: [...FULL_DECK].reverse().slice(0, 25), timings: [1, 2, 3] }, Buffer.alloc(32, 7));
  assert.equal(result.mnemonic.split(' ').length, 24);
  assert.equal(result.entropyHex.length, 64);
  assert.ok(result.cardSpaceBits > 256);
});

test('duplicate card is rejected', () => {
  const deck = [...FULL_DECK].slice(0, 25); deck[24] = deck[0];
  assert.throws(() => generateFromCards({ deck1: deck, deck2: [...FULL_DECK].slice(25, 50) }, Buffer.alloc(32)), /nie może się powtarzać/);
});
