# LineageOS 22.2 unofficial для courbet (Mi 11 Lite 4G)

Сборка через GitHub Actions: `.github/workflows/build-lineage-courbet.yml`.
Запуск: Actions → `Build LineageOS 22.2 unofficial (courbet)` → Run workflow.

## Что внутри

- База: `LineageOS/android.git`, ветка `lineage-22.2` (Android 15 QPR2).
- Device: `abdalrahmaneissa/android_device_xiaomi_courbet@lineage` + `sm6150-common@lineage`.
- Вендоры: `courbet@main` + `TheMuppets/sm6150-common@lineage-22.2`.
- Ядро: `LineageOS/android_kernel_xiaomi_sm6150@lineage-22.2` как best-effort
  (у автора device tree нет своего kernel-репозитория; `preflight.sh`
  подменяет отсутствующий `courbet_defconfig` на `vendor/sdmsteppe_defconfig`).
- Фикс битого `lineage.dependencies` (лишняя запятая) делается в `preflight.sh`.

Полный манифест: `lineage-courbet/local_manifests/courbet.xml`.

## Честные ограничения

1. Официального Lineage под courbet нет, это unofficial-порт 2025 года.
2. Раннер `ubuntu-22.04` чистится перед синком, но места/RAM/6ч лимита
   может не хватить: синк ~100 ГБ, сборка несколько часов.
   Если упадёт по диску/OOM/timeout — это ожидаемый исход бесплатного раннера,
   логи и частичный `out/` попадут в артефакты.
3. Ядро-подмена может не загрузиться на железе даже при успешной сборке —
   у `sm6150`-ядра нет `courbet.config`, только `sdmsteppe/atoll/sweet/toco` и др.
   Заливать только через recovery с бэкапом стока.

## Артефакты

`lineage-22.2-courbet-unofficial`: `lineage-*.zip`, `recovery.img`, `boot.img`, `build-courbet.log`.
