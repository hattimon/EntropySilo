import { createHash, randomBytes } from 'node:crypto';
import { entropyToMnemonic } from './bip39.js';

export const RANKS = Object.freeze(['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']);
export const SUITS = Object.freeze(['S', 'H', 'D', 'C']);
export const FULL_DECK = Object.freeze(SUITS.flatMap((suit) => RANKS.map((rank) => `${rank}${suit}`)));

export const CARDS_PER_DRAW = 25;

function validateDraw(deck, label) {
  if (!Array.isArray(deck) || deck.length !== CARDS_PER_DRAW) throw new Error(`${label}: wymagane jest dokładnie 25 kolejnych kart.`);
  const normalized = deck.map((card) => String(card).trim().toUpperCase());
  if (new Set(normalized).size !== CARDS_PER_DRAW || normalized.some((card) => !FULL_DECK.includes(card))) {
    throw new Error(`${label}: 25 kart musi być prawidłowych i nie może się powtarzać.`);
  }
  return normalized;
}

export function generateFromCards({ deck1, deck2, timings = [], salt = '' }, systemEntropy = randomBytes(32)) {
  const first = validateDraw(deck1, 'Losowanie 1');
  const second = validateDraw(deck2, 'Losowanie 2');
  if (asBytes(systemEntropy).length !== 32) throw new Error('Losowość systemowa musi mieć 256 bitów.');
  const timingDigest = createHash('sha256').update(JSON.stringify(timings)).digest();
  const entropy = createHash('sha256')
    .update('EntropySilo/card-entropy/25+25/v3\0', 'utf8')
    .update(first.join(','), 'ascii').update('\0')
    .update(second.join(','), 'ascii').update('\0')
    .update(String(salt).normalize('NFKD'), 'utf8').update('\0')
    .update(timingDigest).update(asBytes(systemEntropy)).digest();
  const result = entropyToMnemonic(entropy);
  timingDigest.fill(0); entropy.fill(0);
  return { ...result, source: '25+25-cards+timing+system-csprng', cardSpaceBits: 264.8883245890461 };
}

function asBytes(value) { return Buffer.from(value); }
