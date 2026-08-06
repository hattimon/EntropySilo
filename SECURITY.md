# Security model

**Language:** [🇬🇧 English](SECURITY.md) | [🇵🇱 Polski](SECURITY.pl.md)

## Protected data

The vault never stores a plaintext mnemonic or private key. It stores an SWD recovery code, WIF or legacy-mode input inside an AES-256-GCM encrypted document. A key is derived from the 12-digit PIN with scrypt (`N=131072`, `r=8`, `p=1`) and a random salt. EntropySilo vault format v3 authenticates public provenance metadata as additional authenticated data (AAD); changing the ciphertext, metadata or GCM tag causes rejection. Legacy RPiWallet v1/v2 vaults remain readable solely for migration.

A secret must nevertheless be decrypted briefly in RAM to derive a key or sign a PSBT. Signing from a one-way hash alone is impossible. Sensitive operations run in a short-lived Node.js process, while swap, core dumps and persistent logs are disabled. After the one-time recovery-backup screen, onboarding replaces the running GUI with a fresh process.

## Entropy

Every newly generated 24-word wallet starts with exactly 256 bits of entropy followed by the 8-bit BIP39 checksum. System generation requests exactly 32 bytes from Node.js `crypto.randomBytes`, backed by the operating system cryptographic random-number generator; it never uses `Math.random`. The call may block until the operating system has initialized its entropy pool.

Card generation requires two independent ordered draws of 25 unique cards from a complete, freshly reshuffled deck. The ordered input space is `(52P25)^2`, approximately `2^264.89`. Both draws, interaction timings, an optional user phrase and an independent 32-byte `crypto.randomBytes` value are combined using a domain-separated SHA-256 construction. Cards are an additional source: weak or predictable shuffling does not reduce the quality of the independent operating-system CSPRNG contribution. The generator does not truncate a smaller pool or use biased modulo reduction.

## System isolation

- The GUI service is denied all network address families except `AF_UNIX`.
- nftables drops input, output and forwarding traffic.
- udev rules prevent network interfaces from being activated.
- SSH, DHCP/NetworkManager, Avahi, wpa_supplicant and Bluetooth services are masked.
- Wi-Fi and Bluetooth kernel modules are blacklisted.
- Swap and core dumps are disabled; `/tmp` and `/var/tmp` use tmpfs.
- The `wallet` account has no shell or password and can write only to its private data directory.
- The GUI uses `NoNewPrivileges=yes` and never invokes `sudo`. The final image removes `sudo`; shutdown and the closed set of USB operations are handled by a separate root service reached through a Unix socket.
- The broker validates every operation name and input/output size. Only the `wallet` group can access its socket.
- A data USB drive is mounted for one operation with `noexec,nosuid,nodev`. The helper accepts FAT32/exFAT, exactly one eligible data device and strict filenames under `/EntropySilo`. PSBT inputs must be regular, non-symlink files, are limited to 2 MiB and must have a permitted name.
- New HID keyboard hot-plug is blocked by default. Settings can open a 60-second pairing window.

## USB backup

A backup places existing encrypted vault documents inside a second AES-256-GCM layer protected by a separate password of at least 12 characters, hardened with scrypt. It is streamed directly to the USB helper and is not staged as a plaintext or temporary backup file on the SD card.

The helper creates `/EntropySilo/backup.eswb`, then the first free `backup1.eswb`, `backup2.eswb`, and so on. It never overwrites or deletes unrelated files. Legacy `.rpwb` files are accepted only for restore and reserve their number in the same sequence. A portable disaster-recovery backup cannot be bound cryptographically to one Raspberry Pi without defeating restoration after device loss; its protection therefore depends on a strong, separate backup password.

## Hardware limitations

Raspberry Pi 2 and microSD provide no secure element, tamper resistance, monotonic attempt counter, trustworthy secure boot or administrator-resistant secret storage. An attacker holding the SD card can copy an encrypted vault and attempt PIN guesses offline. scrypt raises the cost, but twelve decimal digits are not equivalent to a high-entropy passphrase or a secure element.

The device cannot detect every supply-chain attack, malicious SD-controller firmware, compromised display/keyboard firmware or physical implant. Do not connect untrusted USB devices. Build from a clean workstation, verify `SHA256SUMS`, and retain your own reviewed source copy.

## Operating assumptions

1. The device remains physically air-gapped and Ethernet stays disconnected.
2. The user verifies every destination, amount, change output and fee on the trusted screen before signing.
3. A paper or metal copy of the 24 words or SWD code is stored separately.
4. Before protecting material funds, the source and image receive independent review and the full workflow is tested on testnet or with a small amount.
5. Losing both the PIN and the recovery backup means permanent loss of access.

## Factory reset

Factory reset requires the correct PIN, removes vault files and settings, and returns to first-run setup. Normal deletion on flash media cannot guarantee erasure of historical physical blocks because of wear levelling. Strong encryption remains the protection for historical copies; destroy the SD card physically when retiring the device.

## Trezor

Open-source Trezor code does not turn a Raspberry Pi into a Trezor. Emulators are intended for development and testing, not protection of production keys. EntropySilo therefore does not install or run a Trezor emulator in the production image.
