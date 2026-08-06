TREZOR EMULATOR — INFORMACJA BEZPIECZEŃSTWA
============================================

Ten katalog jest tylko przygotowanym miejscem do przyszłych, odizolowanych
eksperymentów deweloperskich. Emulator Trezora NIE jest częścią obrazu EntropySilo,
nie uruchamia się na starcie i nie wolno używać go z rzeczywistym seedem.

Emulator nie zapewnia zabezpieczeń sprzętowych Trezora, używa środowiska hosta,
a jego mechanizmy losowości i debugowania są przeznaczone do testów. Sam fakt,
że firmware jest open source, nie przenosi właściwości secure elementu,
bootloadera i fizycznego urządzenia na Raspberry Pi.

Jeżeli kiedyś będzie potrzebny do testów:
1. użyj osobnej karty SD i oddzielnego Pi bez prawdziwych skarbców;
2. pobierz źródła na stacji online i przypnij zweryfikowany commit/tag;
3. zbuduj zależności w odtwarzalnym kontenerze, zapisz ich SHA-256;
4. przenieś artefakty jednokierunkowo na środowisko laboratoryjne;
5. stosuj wyłącznie publicznie znane testowe mnemoniki/testnet;
6. po teście zniszcz lub wyczyść kartę laboratoryjną.

Aktualne instrukcje budowy należy zawsze brać z oficjalnego repozytorium
trezor-firmware. Placeholder setup_trezor_emulator.sh celowo niczego nie buduje.
