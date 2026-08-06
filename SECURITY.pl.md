# Model bezpieczeństwa

**Język:** [🇬🇧 English](SECURITY.md) | [🇵🇱 Polski](SECURITY.pl.md)

## Chronione dane

Skarbiec nie zapisuje jawnej mnemoniki ani kluczy prywatnych. Zapisuje kod odzyskiwania SWD, WIF albo dane wejściowe trybu legacy wewnątrz dokumentu szyfrowanego AES-256-GCM. Klucz jest wyprowadzany z 12-cyfrowego PIN-u przez scrypt (`N=131072`, `r=8`, `p=1`) z losową solą. Format EntropySilo v3 uwierzytelnia także publiczne metadane pochodzenia jako AAD; zmiana ciphertextu, metadanych lub tagu GCM powoduje odrzucenie. Odczyt starszych formatów RPiWallet v1/v2 pozostaje możliwy wyłącznie dla migracji.

Sekret musi jednak zostać na krótko odszyfrowany w RAM, aby wyprowadzić klucz lub podpisać PSBT. Nie istnieje sposób podpisywania z użyciem samego nieodwracalnego hasha. Operacje są wykonywane w krótkotrwałym procesie Node, a swap, core dump i trwałe logi są wyłączone. Po jednorazowym ekranie kopii onboarding zastępuje bieżący proces świeżym procesem GUI.

## Entropia

Nowy portfel ma zawsze 256 bitów entropii przed 8-bitowym checksumem BIP-39, czyli 24 słowa. Tryb systemowy pobiera dokładnie 32 bajty z `crypto.randomBytes`, czyli kryptograficznego generatora Node.js zasilanego przez system operacyjny; nie używa `Math.random`. Wywołanie może czekać, dopóki system nie zgromadzi wystarczającej entropii. Tryb kart wymaga dwóch niezależnych losowań po 25 unikalnych kart z pełnej, ponownie tasowanej talii. Przestrzeń uporządkowanych losowań to `(52P25)^2`, około `2^264,89`. Wynik jest domenowo separowanym SHA-256 z obu losowań, czasów interakcji i niezależnych 32 bajtów `crypto.randomBytes`. Karty są dodatkowym źródłem; wadliwe lub przewidywalne tasowanie nie może obniżyć jakości systemowego CSPRNG. Generator nie stosuje skracania, modulo ani puli o ograniczonej liczbie stanów.

## Izolacja systemu

- wszystkie rodziny adresów sieciowych poza `AF_UNIX` są zabronione usłudze GUI;
- nftables blokuje wejście, wyjście i forwarding;
- reguły udev nie pozwalają aktywować interfejsów sieciowych;
- SSH, DHCP/NetworkManager, Avahi, wpa_supplicant i Bluetooth są zamaskowane;
- moduły Wi-Fi/Bluetooth są blacklistowane;
- swap i core dump są wyłączone, `/tmp` i `/var/tmp` są tmpfs;
- konto `wallet` nie ma powłoki ani hasła; zapis jest ograniczony do prywatnego katalogu danych;
- GUI działa z `NoNewPrivileges=yes` i nie używa `sudo`; pakiet `sudo` jest usuwany z gotowego obrazu, a wyłączenie oraz zamknięty zestaw operacji USB obsługuje osobna usługa root uruchamiana gniazdem Unix;
- broker sprawdza nazwę operacji i limity wejścia/wyjścia, a dostęp do jego gniazda ma tylko grupa `wallet`;
- pendrive jest montowany tylko na czas jednej operacji z `noexec,nosuid,nodev`; helper akceptuje FAT32/exFAT, dokładnie jeden nośnik i wyłącznie ustalone nazwy w `/EntropySilo`; pliki PSBT muszą być zwykłymi plikami, nie dowiązaniami, mają limit 2 MiB i rygorystyczną nazwę;
- hot-plug nowej klawiatury HID jest domyślnie blokowany; 60-sekundowe okno parowania można otworzyć w ustawieniach.

## Backup USB

Backup zawiera istniejące, już zaszyfrowane skarbce wewnątrz drugiej warstwy AES-256-GCM chronionej osobnym hasłem (minimum 12 znaków, scrypt). Jest przesyłany bezpośrednio z procesu do helpera USB i nie jest zapisywany jako plik roboczy na karcie SD. Helper tworzy wyłącznie `/EntropySilo/backup.eswb`, a następnie pierwszą wolną nazwę `backup1.eswb`, `backup2.eswb` itd. Nie nadpisuje ani nie usuwa innych plików. Starsze pliki `.rpwb` są akceptowane wyłącznie przy odtwarzaniu i zajmują swój numer w tej samej sekwencji. Portable backup nie może być kryptograficznie związany wyłącznie z jednym egzemplarzem Raspberry Pi, ponieważ uniemożliwiłoby to odtworzenie po awarii urządzenia; ochronę stanowi osobne silne hasło.

## Ograniczenia sprzętowe

Raspberry Pi 2 i karta microSD nie zapewniają secure elementu, anti-tamper, monotonicznego licznika prób, wiarygodnego secure boot ani ochrony klucza przed administratorem z fizycznym dostępem. Atakujący posiadający kartę SD może skopiować skarbiec i prowadzić offline próby PIN-u. Scrypt podnosi koszt, ale 12 cyfr nie zastępuje losowej silnej frazy ani secure elementu.

Urządzenie nie może wykryć wszystkich ataków supply-chain, złośliwego firmware'u kontrolera SD, zmanipulowanego wyświetlacza/klawiatury ani fizycznych implantów. Nie podłączaj niezaufanych urządzeń USB. Buduj z czystej stacji, sprawdzaj `SHA256SUMS` i przechowuj własną kopię źródeł.

## Założenia użycia

1. Pi pozostaje fizycznie air-gapped; Ethernet jest odłączony.
2. Użytkownik sprawdza adres odbiorcy, kwotę, zmianę i opłatę na zaufanym ekranie przed podpisem.
3. Papierowa/metalowa kopia 24 słów lub kodu SWD jest przechowywana osobno.
4. Dla istotnych środków kod i obraz przechodzą niezależny audyt, a cały przepływ jest najpierw testowany na testnecie lub małej kwocie.
5. Utrata PIN-u i kopii odzyskiwania oznacza trwałą utratę dostępu.

## Reset fabryczny

Reset wymaga poprawnego PIN-u, usuwa pliki skarbców i ustawienia, a potem uruchamia kreator od początku. Na pamięci flash zwykłe usunięcie pliku nie gwarantuje fizycznego wymazania wszystkich wcześniejszych bloków z powodu wear levelling. Dlatego ochroną kopii historycznych pozostaje silne szyfrowanie; przy wycofaniu urządzenia należy fizycznie zniszczyć kartę SD.

## Trezor

Kod open-source Trezora nie zmienia Raspberry Pi w Trezora. Emulator jest przeznaczony do rozwoju i testów, a nie do ochrony rzeczywistych kluczy. Z tego powodu nie jest instalowany ani uruchamiany w obrazie produkcyjnym.
