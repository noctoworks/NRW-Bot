# Карта модулей и владения

Фундамент (config/models/mock-remnawave/payment-stub/dispatcher/miграции) — готов,
см. коммиты `Foundation scaffold`, `Add cross-module service contracts`, `Add seed script`.

| Модуль | Файлы | Статус | Зависит от |
|---|---|---|---|
| Регистрация/главное меню | `app/handlers/start.py` | TODO | `app/keyboards/main_menu.py`, `app/services/gift_service.py`, `app/services/referral_service.py` |
| Подписка (покупка/продление/устройства) | `app/handlers/subscription.py` | TODO | `app/external/remnawave`, `app/services/payment`, `app/services/referral_service.py`, `app/services/notification_service.py` |
| Реферал/промокод/подарок | `app/handlers/referral.py`, `app/handlers/promocode.py`, `app/handlers/gift.py`, + реализация `app/services/{referral,gift,promocode}_service.py` | TODO | — |
| Админка/поддержка/фон/уведомления | `app/handlers/admin.py`, `app/handlers/support.py`, `app/services/notification_service.py` (реализация), `app/services/background.py` (новый), хук в `main.py` | Готово | — |

Единая точка регистрации хендлеров — `app/handlers/__init__.py`, каждый модуль
добавляет туда ровно одну строку (уже подготовлено).

Архитектурный документ (полная спецификация, все sequence-диаграммы):
https://claude.ai/code/artifact/3ec7e422-b599-49a8-b04d-f6514579382d
