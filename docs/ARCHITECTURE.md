# UEFI для Xiaomi Mi 11 Lite 4G (courbet)

Цель: UEFI-прошивка с графическим меню загрузки на Snapdragon 732G (SM7325),
с перспективой последующей загрузки Windows 11 ARM64.

## Аппаратная база (проверено разбором `boot.img`)

| | |
|---|---|
| Устройство | Mi 11 Lite 4G, кодовое имя `courbet` |
| SoC | Snapdragon 732G (SM7325), Cortex-A76 + A55 |
| Раздел `boot` | 128 МиБ, из них занято 16.35 МиБ |
| Свободно | **111.65 МиБ** — UEFI помещается с большим запасом |
| Загрузчик | разблокирован пользователем |

`boot.img` — стандартный Android boot image, заголовок помечен `header_version=2`,
но физически собран по раскладке v0/v1: магия v2 (`0x2FFE6506`) по смещению 1636
отсутствует, в слоте `header_size` лежит мусор. Упаковщик это учитывает
(`tools/repack.py`, проверка `has_v2_magic`), иначе он бы считал заголовок
398043 байт и разъехался бы по смещениям payload.

## Транспорт: как UEFI вообще попадёт на устройство

Ключевая идея — **подменить ядро в `boot.img` PE32+-приложением EFI**.

Вендорский загрузчик отдаёт слот ядра в загрузчик образов UEFI. Если там лежит
валидное EFI-приложение, оно стартует как UEFI-приложение, и вся машина
переходит под управление нашего EDK2: ACPI, GOP, BDS, boot manager. Дальше
остаётся только найти, откуда грузить Windows.

```
SBL -> XBL -> [загрузчик образов UEFI] -> наш payload.efi -> BdsDxe -> Windows ARM64
                                  ^
                   сюда кладём PE32+ AArch64 вместо ядра
```

### Открытый вопрос, который решается первым

Точный тип загрузчика на courbet (U-Boot или ABL/EDK2) determines, сработает ли
подмена. Признаки в cmdline указывают на **U-Boot**:

```
video=vfb:640x400,bpp=32,memsize=3072000    <- настройка фреймбуфера U-Boot
loop.max_part=7
```

Это нужно подтвердить экспериментально до того, как строить полноценный
интерфейс. Поэтому работа разбита на этапы, и первый этап — диагностический,
а не «красивый».

## Этапы

### Этап 1 — транспорт (диагностика)
Цель: доказать, что payload вообще запускается, и вернуть телефон в Android.

- Собрать базовый `UefiPayloadPkg` для AARCH64 (содержит `BdsDxe` + `UiApp`).
- Проверить на хосте, что это валидный PE32+ AArch64 EFI-приложение.
- Заменить ядро в `boot.img`, прошить.
- Критерий успеха: UEFI стартует и грузит Android дальше (сохранённое ядро).

Риск минимален: оригинальное ядро лежит в ramdisk-копии и остаётся под рукой.

### Этап 2 — графический интерфейс
- Подключить GOP поверх реального дисплейного конвейера Qualcomm (DSI/GFH/SMDK).
  В `UefiPayloadPkg` для AARCH64 сейчас GOP — QEMU-видео; для SM7325 нужен свой.
- Включить `BOOT_MANAGER_ESCAPE=TRUE` — это включает `UiApp`, графическое меню.

### Этап 3 — ACPI и загрузка Windows ARM64
Windows на ARM требует качественных ACPI-таблиц — без них она не стартует.
- Свой DSDT для SM7325 (у текущего payload DSDT от QEMU).
- Реальные базы GIC, UART, таймера вместо QEMU-значений из DSC.
- Драйверы накопителей: NVMe (уже включён), USB, Virtio — чтобы UEFI увидел
  раздел с Windows.
- Поддержка `Windows on ARM` требует рабочих GPT, EFI System Partition,
  BCD с правильным `efi/application` и `bootmgfw.efi`.

## Структура репозитория

```
.github/workflows/build.yml   сборка через GitHub Actions
scripts/build.sh              сборка EDK2 AArch64 -> out/UefiPayloadPkg.efi
patches/                      патчи к edk2 (заполняются по мере этапов)
PayloadPkg/                   оверлей платформы (позже)
tools/bootimg.py              разбор Android boot image
tools/repack.py               подмена ядра на EFI payload
work/                         рабочие образы (в git не попадает)
```

edk2 в репозиторий не коммитится: CI забирает его сам по зафиксированному SHA
`870158586f14dbf9d57e312ea6ea87141a1b0699`.

## Почему GitHub Actions

На этой машине WSL2 не работает: виртуализация выключена в BIOS, а её включение
требует перезагрузки и физического доступа к машине. Раннер `ubuntu-22.04`
уже содержит весь нужный тулчейн (`gcc-aarch64-linux-gnu`, `uuid-dev`,
`acpica-tools`, `python3`), поэтому CI снимает это ограничение целиком.
Пин 22.04 существенен: на нём Python 3.10, а в более новых дистрибутивах
удалён `distutils`, который ещё нужен BaseTools.

## Что уже проверено

Упаковщик `tools/repack.py` протестирован round-trip'ом на реальном `boot.img`:

```
diffs внутри payload [0, 17141760): 8 байт -> только поле id (576..583)
diffs вне id-поля                     : 0 байт
хвост: оригинал содержал 0.21 МиБ мусора -> обнулён
```

Ядро и ramdisk восстанавливаются побайтово, меняется только целевой payload.

## Прошивка (после успешной сборки)

```bash
# 1. подменить ядро на payload
python tools/repack.py inject \
    "C:\Users\qualixxe\Desktop\boot\boot.img" \
    out\UefiPayloadPkg.efi \
    work\boot-uefi.img

# 2. прошить раздел boot
fastboot flash boot work\boot-uefi.img

# 3. откат — оригинальное ядро
python tools/repack.py inject --no-check \
    "C:\Users\qualixxe\Desktop\boot\boot.img" \
    work\kernel.orig.bin \
    work\boot-stock.img
fastboot flash boot work\boot-stock.img
```

Всегда держи `boot-stock.img` под рукой — это путь возврата в рабочее состояние.
