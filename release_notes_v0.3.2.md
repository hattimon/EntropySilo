# EntropySilo Live USB 0.3.2

## 🇬🇧 English

This platform-specific hotfix replaces the previous x86-64 Live USB image. The Raspberry Pi 2 image remains unchanged at version 0.3.0.

### Fixed

- The 480×320 logical interface is now explicitly scaled to the complete native laptop display instead of being rendered as a small, cropped rectangle.
- Mouse and touch coordinates are translated back to the logical interface, so controls remain aligned at every detected resolution.
- A separate FAT32/exFAT data USB is accepted when Linux reports `TRAN=usb` even if its `RM` removable-media flag is `0`.
- The Live boot device and all of its parent devices remain explicitly excluded from data-drive selection.
- Encrypted backups are read from `/EntropySilo`; legacy `.rpwb` backups and the old `/RPiWallet` folder remain read-only compatible.

### Important

Use a **second** FAT32/exFAT USB drive for imports, PSBT exchange and encrypted backups. The USB drive used to boot EntropySilo is deliberately not selected as a data drive.

Automated application tests, USB-selection regression tests and ISO-structure validation pass. Fullscreen display and backup restore still require confirmation on physical laptop hardware before using substantial funds.

## 🇵🇱 Polski

Ta poprawka dla konkretnej platformy zastępuje poprzedni obraz Live USB x86-64. Obraz Raspberry Pi 2 pozostaje bez zmian w wersji 0.3.0.

### Naprawiono

- Logiczny interfejs 480×320 jest teraz jawnie skalowany do pełnej natywnej rozdzielczości laptopa, zamiast wyświetlać mały, ucięty prostokąt.
- Współrzędne myszy i dotyku są przeliczane z powrotem na logiczny interfejs, dzięki czemu kontrolki pozostają zgodne przy każdej wykrytej rozdzielczości.
- Osobny pendrive FAT32/exFAT jest akceptowany, gdy Linux zgłasza `TRAN=usb`, nawet jeśli flaga nośnika wymiennego `RM` wynosi `0`.
- Nośnik startowy Live oraz wszystkie jego urządzenia nadrzędne pozostają jawnie wykluczone z wyboru nośnika danych.
- Szyfrowane backupy są odczytywane z `/EntropySilo`; starsze kopie `.rpwb` i dawny katalog `/RPiWallet` pozostają zgodne wyłącznie do odczytu.

### Ważne

Do importu, wymiany PSBT i szyfrowanych backupów użyj **drugiego** pendrive'a FAT32/exFAT. Pendrive, z którego uruchomiono EntropySilo, celowo nie jest wybierany jako nośnik danych.

Testy automatyczne aplikacji, regresyjne testy wyboru USB i walidacja struktury ISO przechodzą poprawnie. Pełny ekran i przywracanie backupu wymagają jeszcze potwierdzenia na fizycznym laptopie przed użyciem większych środków.
