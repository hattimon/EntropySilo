#!/usr/bin/env node
import { generateFromCards } from './card-entropy.js';
const chunks = []; for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk));
const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
console.log(JSON.stringify(generateFromCards(input)));
