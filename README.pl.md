**Język:** [🇬🇧 English](README.md) | [🇵🇱 Polski](README.pl.md)

<p align="center">
  <img src="docs/assets/entropy-silo-logo.svg" alt="EntropySilo — środowisko offline do generowania seedów Bitcoin" width="820">
</p>

<p align="center">
  <strong>Środowisko offline do generowania seedów Bitcoin i podpisywania PSBT</strong><br>
  Generuj świadomie. Odtwarzaj deterministycznie. Podpisuj offline.
</p>

<p align="center">
  <img alt="Sieć: offline" src="https://img.shields.io/badge/sie%C4%87-air--gapped-21c55d?style=flat-square">
  <img alt="Entropia BIP39: 256 bitów" src="https://img.shields.io/badge/entropia_BIP39-256_bit%C3%B3w-21c55d?style=flat-square">
  <img alt="Tylko Bitcoin" src="https://img.shields.io/badge/sie%C4%87-Bitcoin-f7931a?style=flat-square">
  <img alt="Pi 2 zweryfikowany" src="https://img.shields.io/badge/sprz%C4%99t-Pi_2_zweryfikowany-5eff80?style=flat-square&labelColor=102014">
  <img alt="Licencja: MIT" src="https://img.shields.io/badge/licencja-MIT-5eff80?style=flat-square&labelColor=102014">
  <img alt="Wymagany audyt" src="https://img.shields.io/badge/bezpiecze%C5%84stwo-wymagany_niezale%C5%BCny_audyt-d97706?style=flat-square">
</p>

EntropySilo to ukierunkowane na bezpieczeństwo środowisko offline do generowania, odzyskiwania, porządkowania i używania portfeli Bitcoin. Łączy generowanie pełnej entropii BIP39, fizyczną losowość pochodzącą z kart, autorskie projekty hattimon [Seed Generator Wallet Decoder](https://github.com/hattimon/Seed-Generator-Wallet-Decoder) oraz [wallet-decoder](https://github.com/hattimon/wallet-decoder), deterministyczne portfele potomne BIP85, eksport watch-only i podpisywanie transakcji PSBT bez dostępu do sieci.

EntropySilo udostępnia osobne cele budowania dla Raspberry Pi 2 Model B z ekranem Waveshare 3.5inch RPi LCD (A) oraz dla laptopów/PC x86-64 jako Live USB. Wersja 0.3.0 używa nazwy i ścieżek EntropySilo w obu systemach. Obrazy wydania zostaną opublikowane dopiero po przejściu automatycznej walidacji budowy; przed ochroną znacznych środków nadal wymagają potwierdzenia na fizycznym sprzęcie.

> [!WARNING]
> EntropySilo jest eksperymentalnym, niezależnie zbudowanym urządzeniem podpisującym. Nie jest odpowiednikiem certyfikowanego portfela sprzętowego i nie przeszedł jeszcze niezależnego, profesjonalnego audytu bezpieczeństwa. Raspberry Pi 2 nie ma secure elementu, weryfikowanego/mierzonego rozruchu ani obudowy odpornej na manipulacje. Przed ochroną rzeczywistych środków przetestuj odzyskiwanie i cały proces podpisywania na pustym portfelu lub małej kwocie.

## ✨ Dlaczego EntropySilo

- **Pełne 256 bitów entropii BIP39:** każdy nowo generowany portfel wykorzystuje 32 bajty entropii oraz checksum BIP39, tworząc 24-wyrazowy mnemonic.
- **Fizyczna entropia kart:** alternatywna procedura wykorzystuje dwie niezależnie tasowane serie po 25 kart, czasy interakcji, opcjonalną entropię użytkownika oraz niezależny wkład systemowego CSPRNG.
- **Autorska integracja SWD:** odwracalne kody `swd1` i `swd2` pozwalają odtworzyć dokładnie ten sam mnemonic. Osobny tryb legacy realizuje celowo jednokierunkową procedurę wallet-decoder `hasło + liczba`.
- **Praca air-gapped:** generowanie portfela, wyprowadzanie kluczy i podpisywanie transakcji odbywa się bez połączenia sieciowego.
- **Kontrolowane przenoszenie danych:** informacje publiczne i niepodpisane/podpisane PSBT można przenosić kodami QR lub przez ściśle ograniczony mechanizm USB bez eksportowania kluczy prywatnych.
- **Deterministyczna hierarchia:** portfele potomne BIP85 i mapa portfeli pokazują pochodzenie portfeli importowanych oraz wyprowadzonych.
- **Dostępny interfejs:** całość można obsługiwać dotykowo lub klawiaturą USB, w języku polskim i angielskim, w trybie prostym albo zaawansowanym.

## 🖥️ Podgląd interfejsu

Poniższe obrazy są deterministycznymi podglądami dokumentacyjnymi wyrenderowanymi z prawdziwych komponentów GUI 480×320. Nazwy portfeli, adresy i wartości transakcji są danymi demonstracyjnymi — nie zawierają rzeczywistych sekretów ani instrukcji płatniczych.

<table>
  <tr>
    <td width="50%"><img src="docs/assets/main-menu.png" alt="Menu główne EntropySilo"><br><strong>Szybka nawigacja dotykiem i klawiaturą</strong></td>
    <td width="50%"><img src="docs/assets/card-entropy.png" alt="Wprowadzanie entropii kart"><br><strong>Kolejne karty z wyraźnym zielonym oznaczeniem wyboru</strong></td>
  </tr>
  <tr>
    <td><img src="docs/assets/address-standards.png" alt="Standardy adresów Bitcoin"><br><strong>Jednoznacznie oznaczone standardy BIP44/49/84/86</strong></td>
    <td><img src="docs/assets/wallet-map.png" alt="Mapa hierarchii portfeli"><br><strong>Skalowalna mapa pochodzenia i hierarchii BIP85</strong></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="docs/assets/psbt-review.png" alt="Kontrola PSBT offline" width="480"><br><strong>Kontrola portfela, konta, wyjść i opłaty na urządzeniu przed podpisem</strong></td>
  </tr>
</table>

## 🎲 Generowanie entropii

### Systemowy CSPRNG

Generator systemowy pobiera dokładnie 32 bajty za pomocą `crypto.randomBytes` środowiska Node.js, korzystającego z kryptograficznego generatora systemu operacyjnego. Nie używa `Math.random`, nie skraca mniejszej puli losowej i nie redukuje wyniku modulo ograniczonego zakresu.

### Karty i niezależna entropia systemowa

Procedura kart wymaga:

1. wylosowania 25 unikalnych kart z przetasowanej talii 52 kart;
2. pełnego ponownego przetasowania;
3. ponownego wylosowania 25 unikalnych kart;
4. danych czasowych interakcji;
5. opcjonalnej entropii podanej przez użytkownika;
6. niezależnych 32 bajtów systemowego CSPRNG.

Przestrzeń uporządkowanych losowań wynosi `(52P25)^2`, czyli około `2^264,89`. Wszystkie składniki są separowane domenowo i łączone przez SHA-256. Końcowa entropia BIP39 nadal wynosi dokładnie 256 bitów — dodatkowe źródła zwiększają odporność, lecz nie podnoszą bezpieczeństwa ponad 256-bitową przestrzeń wyjściową.

Procedura kart EntropySilo jest niezależną implementacją. **[Rav3nPL](https://github.com/Rav3nPL), autor projektu [Rav3nPL/SeedGenerator](https://github.com/Rav3nPL/SeedGenerator/tree/master), jest wyraźnie wskazany jako pomysłodawca koncepcji SeedGenerator wykorzystującej karty i czasy kliknięć, która zainspirowała ten przepływ.** Kod źródłowy, lista słów, ikony i inne zasoby SeedGeneratora nie są redystrybuowane przez EntropySilo.

## 🔐 Seed Generator Wallet Decoder

EntropySilo integruje autorski projekt hattimon [Seed Generator Wallet Decoder](https://github.com/hattimon/Seed-Generator-Wallet-Decoder):

- `swd1` i `swd2` kodują poprawny mnemonic BIP39 jako kod odzyskiwania złożony z hasła i liczby, a następnie odtwarzają identyczny mnemonic;
- `swd2` używa rozróżniającego wielkość liter alfabetu `a-zA-Z`, dzięki czemu krócej koduje prefiks entropii;
- tryb legacy jest zgodny z algorytmem autorskiego projektu hattimon [wallet-decoder](https://github.com/hattimon/wallet-decoder) i jest celowo jednokierunkowy;
- obsługiwane są końcówki liczby słów `:12` i `:24`, a po pominięciu końcówki przyjmowane są 24 słowa.

Hasło i liczba SWD zawierają tę samą tajną entropię co reprezentowany przez nie mnemonic. Stanowią alternatywną reprezentację danych odzyskiwania i należy wykonywać ich kopię oraz chronić je równie starannie jak słowa seed.

## ₿ Funkcje portfela Bitcoin

- import BIP39 i generowanie 24 słów;
- BIP44 Legacy (`m/44'/0'/...`);
- BIP49 Nested SegWit (`m/49'/0'/...`);
- BIP84 Native SegWit (`m/84'/0'/...`);
- BIP86 Taproot (`m/86'/0'/...`);
- deterministyczne mnemoniki potomne BIP85;
- podgląd adresów publicznych i kodów QR;
- eksport deskryptorów watch-only i rozszerzonych kluczy publicznych;
- wybór portfela, konta, gałęzi change oraz indeksu adresu;
- interaktywna mapa pochodzenia portfeli;
- kontrola i podpisywanie PSBT offline;
- import przez obraz QR, kamerę UVC, urządzenie HDMI-USB albo plik USB;
- szyfrowane, numerowane backupy USB bez nadpisywania istniejących plików.

## 🛡️ Architektura bezpieczeństwa

- skarbiec szyfrowany AES-256-GCM;
- klucz wyprowadzany z 12-cyfrowego PIN-u przez scrypt (`N=131072`, `r=8`, `p=1`);
- uwierzytelnione metadane pochodzenia w aktualnym formacie skarbca;
- wyłączony swap, core dump i trwałe logi aplikacji;
- izolacja GUI przez `NoNewPrivileges=yes`;
- brak pakietu `sudo` w gotowym obrazie urządzenia;
- wąski broker operacji uprzywilejowanych dostępny wyłącznie przez lokalne gniazdo Unix;
- polityka nftables drop-all oraz wyłączone i zamaskowane usługi sieciowe;
- blacklistowane moduły Wi-Fi i Bluetooth;
- nośniki wymienne montowane wyłącznie na czas jednej operacji z `noexec,nosuid,nodev`;
- operacje USB ograniczone do zwykłych plików o ograniczonym rozmiarze w `/EntropySilo`;
- szyfrowane backupy przesyłane bezpośrednio na USB bez jawnego pliku roboczego na karcie SD.

Sekrety muszą na krótko pojawić się w RAM podczas wyprowadzania klucza lub podpisywania transakcji. Uniwersalne Raspberry Pi nie może zagwarantować ochrony przed wrogim administratorem, złośliwym firmware'em, implantami sprzętowymi ani analizą skopiowanego nośnika. Przed użyciem przeczytaj pełny [model bezpieczeństwa](SECURITY.md).

## 🎛️ Interfejs i obsługa

- kreator pierwszego uruchomienia po polsku i angielsku, domyślnie po angielsku;
- tryb Simple prowadzący przez odbieranie, eksport watch-only i podpisywanie transakcji;
- tryb zaawansowany z obsługą ścieżek, standardów portfeli, BIP85 i ustawień specjalistycznych;
- sterowanie dotykowe i pełna nawigacja klawiaturą USB;
- klawiatura ekranowa obsługiwana strzałkami i klawiszem Enter;
- reset fabryczny chroniony PIN-em;
- pięć lekkich motywów: Mono, Phosphor, Amber, Cobalt i Crimson.

## 💾 Struktura USB

Katalog wymiany USB to `/EntropySilo` zarówno w edycji Raspberry Pi 2, jak i Live USB.

```text
/EntropySilo/
├── import.txt
├── transaction.psbt
├── unsigned-qr.png
├── backup.eswb
├── backup1.eswb
└── backup2.eswb
```

Aplikacja nigdy nie uruchamia skryptów z nośnika wymiennego. Obsługuje wyłącznie jawnie wspierane pliki w tym katalogu i nie usuwa ani nie nadpisuje pozostałych danych.

## 📦 Oficjalne pobieranie

**Jedynym oficjalnym kanałem dystrybucji** są [wydania GitHub Releases](https://github.com/hattimon/EntropySilo/releases). Obrazy systemu są załącznikami wydań i nigdy nie trafiają bezpośrednio do historii repozytorium Git.

Każdemu obrazowi do pobrania muszą towarzyszyć:

- dokładna wersja i platforma sprzętowa w nazwie pliku;
- plik sumy kontrolnej `.sha256`;
- odpowiadający raport zgodności i walidacji `.txt`;
- informacje o zmianach istotnych dla bezpieczeństwa.

Przed zapisaniem obrazu na kartę SD albo USB zawsze zweryfikuj SHA-256. Zapasowy mirror może zostać później ogłoszony przez hattimon, lecz nie zastąpi GitHub Releases jako źródła oficjalnego.

## 🧩 Obsługiwany sprzęt i obrazy

| Platforma | Architektura | Ekran | Status |
|---|---:|---|---|
| Raspberry Pi 2 Model B | ARMv7 / 32-bit | Waveshare 3.5inch RPi LCD (A), 480x320 | Budowa 0.3.0 ukończona; wydana w release v0.3.0 GitHub |
| Raspberry Pi 3 | ARM64 | Waveshare 3.5inch RPi LCD (A) | Planowany osobny obraz |
| Raspberry Pi 4/5 | ARM64 | Waveshare 3.5inch RPi LCD (A) | Planowany osobny obraz |
| PC Live USB | x86-64 | Standardowy ekran, klawiatura, mysz/dotyk i kamera UVC | Budowa 0.3.0 ukończona; wydana w release v0.3.0 GitHub |

Artefakty wydania EntropySilo 0.3.0 (dostępne w [wydaniu v0.3.0 na GitHub](https://github.com/hattimon/EntropySilo/releases/tag/v0.3.0)):

```text
EntropySilo-Pi2-Bookworm-0.3.0.img.xz
EntropySilo-Live-x86_64-0.3.0.iso
```

Każdy przyszły obraz otrzyma odpowiadający mu raport zgodności `.txt`. Platforma nie zostanie opisana jako zweryfikowana, dopóki cały proces rozruchu, obrazu, sterowania, backupu, odzyskiwania i podpisywania PSBT nie zostanie sprawdzony na fizycznym sprzęcie.

## 🏗️ Budowanie obrazu Pi 2

Wymagania: Windows z WSL2/Ubuntu albo Linux x86-64, około 15 GB wolnego miejsca i sieć wyłącznie na komputerze budującym.

Windows PowerShell:

```powershell
Set-Location <ścieżka-do>\EntropySilo
.\image-builder\build_from_windows.ps1
```

Linux:

```bash
bash image-builder/prepare_assets.sh
sudo bash image-builder/build_image.sh
```

Budowniczy pobiera oficjalną bazę Raspberry Pi OS Lite, weryfikuje przypięte zasoby, provisionuje obraz pod QEMU, wykonuje kryptograficzne testy regresji i tworzy skompresowany obraz wraz z sumą SHA-256.

## 💻 Budowanie obrazu Live USB x86-64

Edycja Live jest osobnym hybrydowym ISO Debian Bookworm dla 64-bitowych laptopów i komputerów PC. Obsługuje start BIOS i UEFI, uruchamia interfejs pełnoekranowo, wyłącza sieć oraz przechowuje skarbiec w nietrwałej warstwie systemu Live. Zmiany skarbca znikają po wyłączeniu. Do importu, PSBT i szyfrowanych backupów używaj **drugiego** pendrive'a FAT32/exFAT z katalogiem `/EntropySilo`; nośnik startowy jest jawnie wykluczony z wyboru nośnika danych.

Windows PowerShell z WSL2/Ubuntu:

```powershell
Set-Location <ścieżka-do>\EntropySilo
.\live-builder\build_from_windows.ps1
```

Linux/Debian lub Ubuntu:

```bash
sudo ./live-builder/setup_build_host.sh
sudo ./live-builder/build_live.sh
```

Powstały plik `.iso` zapisz w trybie surowym/DD przez Raspberry Pi Imager, balenaEtcher, Rufus w trybie DD albo `dd`. Zgodność Secure Boot zależy od firmware konkretnego komputera i wymaga sprawdzenia na docelowym laptopie. Generowany raport `.txt` celowo odróżnia walidację struktury obrazu od walidacji na rzeczywistym sprzęcie.

## ✅ Testy deweloperskie

```bash
npm ci
npm test
npm run check
npm audit --omit=dev
```

Testy obejmują BIP39, łączenie entropii kart, szyfrowane skarbce, oficjalny wektor BIP85, rzeczywisty przepływ podpisu PSBT BIP84, ochronę przed nadpisaniem skarbca, uprawnienia gniazda brokera i nawigację GUI klawiaturą.

## 👤 Autorstwo i przypisanie projektów

EntropySilo, [hattimon/Seed-Generator-Wallet-Decoder](https://github.com/hattimon/Seed-Generator-Wallet-Decoder) oraz [hattimon/wallet-decoder](https://github.com/hattimon/wallet-decoder) są projektami autorstwa **hattimon**.

**[Rav3nPL](https://github.com/Rav3nPL) jest autorem i pomysłodawcą zewnętrznego projektu [SeedGenerator](https://github.com/Rav3nPL/SeedGenerator/tree/master) oraz zastosowanej w nim koncepcji generowania z kart i czasów kliknięć, która zainspirowała powiązany przepływ EntropySilo.** EntropySilo nie przypisuje sobie autorstwa SeedGeneratora i nie redystrybuuje jego implementacji ani zasobów.

Zewnętrzne biblioteki kryptograficzne zachowują własne licencje i informacje prawne.

## 📜 Licencja open source

EntropySilo jest udostępniany na [licencji MIT](LICENSE). Możesz używać, analizować, modyfikować i rozpowszechniać projekt z zachowaniem informacji o prawach autorskich i treści licencji. Dołączone zależności oraz komponenty zewnętrzne zachowują własne licencje i noty prawne.

## ❤️ Wesprzyj projekt

Jeżeli EntropySilo jest dla Ciebie przydatny, możesz zostawić hattimon dobrowolny napiwek i pomóc sfinansować testy sprzętowe, przeglądy bezpieczeństwa oraz dalszy rozwój otwartego oprogramowania.

Planowane kanały wsparcia są dobrane tak, aby wpłaty były możliwie tanie zarówno w Polsce, jak i za granicą:

| Metoda | Najlepsze zastosowanie | Model kosztów |
|---|---|---|
| **⚡ Bitcoin Lightning przez osobny portfel darowizn [BTCPay Server](https://docs.btcpayserver.org/Guide/)** | Małe napiwki międzynarodowe | Bez prowizji platformy; zwykle niewielka opłata routingu. Internetowy portfel Lightning musi pozostać oddzielony od seedów EntropySilo. |
| **₿ Bitcoin on-chain** | Większe napiwki międzynarodowe | Bezpośrednia wpłata bez operatora płatności; nadawca ponosi opłatę sieci Bitcoin. |
| **💳 [GitHub Sponsors](https://github.com/sponsors)** | Zagraniczne karty i wsparcie cykliczne | GitHub obecnie przekazuje 100% wpłat z kont osobistych sponsorów wspieranemu twórcy; warunki wypłaty i przewalutowania określa Stripe. |
| **🇵🇱 [Zrzutka.pl](https://zrzutka.pl/how-it-works/support/donate)** | BLIK, polskie karty, Apple Pay, Google Pay i szybkie przelewy | Podstawowa usługa deklaruje brak obowiązkowej prowizji; wsparcie platformy oraz usługi premium pozostają dobrowolne. |

Oficjalne dane do wpłat zostaną dodane wyłącznie po zweryfikowaniu adresów i profili przez hattimon. Nigdy nie wysyłaj środków na adres podany w zgłoszeniu, pull requeście, komentarzu ani niezamówionej wiadomości prywatnej.
