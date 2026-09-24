"""Реестр автоматических сообщений бота: события, заводские тексты, переменные.

Заводские тексты — ДОСЛОВНО те, что раньше были зашиты в notification_service.py; они же служат
запасным вариантом, если правки владельца не заданы, выключены или отклонены Telegram.
Правки хранятся в таблице message_templates (см. service.py)."""

from __future__ import annotations

from dataclasses import dataclass


class UnknownEventError(KeyError):
    """Ключа события нет в реестре."""


@dataclass(frozen=True)
class Variable:
    name: str
    description: str
    example: str


@dataclass(frozen=True)
class EventDef:
    key: str
    group: str
    title: str
    trigger: str
    default_template: str
    variables: tuple[Variable, ...] = ()
    required_variables: tuple[str, ...] = ()
    default_button_text: str | None = None
    # Только у welcome_nudge: без MINIAPP_URL кнопка называется иначе (запасной callback).
    default_button_text_no_miniapp: str | None = None

    @property
    def variable_names(self) -> tuple[str, ...]:
        return tuple(variable.name for variable in self.variables)

    @property
    def has_button(self) -> bool:
        return self.default_button_text is not None

    def samples(self) -> dict[str, str]:
        return {variable.name: variable.example for variable in self.variables}

    def button_label(self, miniapp_enabled: bool) -> str | None:
        if self.default_button_text is None:
            return None
        if not miniapp_enabled and self.default_button_text_no_miniapp is not None:
            return self.default_button_text_no_miniapp
        return self.default_button_text


_AMOUNT = Variable('amount', 'Сумма в рублях числом, без знака ₽ (например 249.00)', '249.00')
_DISCOUNT_PERCENT = Variable('discount_percent', 'Размер скидки в процентах числом, без знака % (например 20)', '20')
_UNTIL = Variable('until', 'До какого момента действует скидка, по Москве (например «27.09 в 15:00 МСК»)', '27.09 в 15:00 МСК')

EVENTS: tuple[EventDef, ...] = (
    EventDef(
        key='payment_success',
        group='Платежи',
        title='Оплата прошла',
        trigger='Платёж подтверждён: покупка, продление подписки или автоплатёж',
        default_template='✅ Оплата на сумму {amount}₽ прошла успешно. {description}',
        variables=(_AMOUNT, Variable('description', 'Что оплачено (например «Подписка «Онлайн» на 30 дн.»)', 'Подписка «Онлайн» на 30 дн.')),
    ),
    EventDef(
        key='referral_bonus',
        group='Рефералы',
        title='Реферальное начисление',
        trigger='Приглашённый вами пользователь оплатил — вам начислена комиссия',
        default_template='🎉 Вам начислено {amount}₽ реферальных бонусов!',
        variables=(Variable('amount', 'Сумма комиссии в рублях числом, без знака ₽', '25.00'),),
    ),
    EventDef(
        key='referral_invite_bonus',
        group='Рефералы',
        title='Бонус за приглашённого друга',
        trigger='Друг зарегистрировался по вашей ссылке — вам начислены дни подписки',
        default_template=(
            '🚀 По вашей ссылке зарегистрировался друг — начислено +{bonus_days} дн. подписки!\n\n'
            'Приглашайте ещё — бонус начисляется за каждого нового друга.'
        ),
        variables=(Variable('bonus_days', 'Сколько дней подписки начислено', '3'),),
    ),
    EventDef(
        key='subscription_expiring',
        group='Подписка',
        title='Подписка скоро истечёт',
        trigger='За 3 дня и за 1 день до окончания подписки',
        default_template='⏳ Ваша подписка истекает через {days_left} дн.',
        variables=(Variable('days_left', 'Сколько дней осталось (3 или 1)', '3'),),
    ),
    EventDef(
        key='subscription_expired',
        group='Подписка',
        title='Подписка истекла',
        trigger='Подписка закончилась',
        default_template='❌ Ваша подписка истекла. Продлите её в главном меню.',
    ),
    EventDef(
        key='trial_ending',
        group='Подписка',
        title='Пробный период скоро закончится',
        trigger='За 1 день до конца пробного периода, пока действует скидка (вместо обычного напоминания)',
        default_template=(
            '⏳ Пробный период заканчивается завтра. Оформите подписку со скидкой {discount_percent}% — '
            'предложение действует до {until}.'
        ),
        variables=(_DISCOUNT_PERCENT, _UNTIL),
        default_button_text='💎 Подключиться со скидкой',
    ),
    EventDef(
        key='trial_expired',
        group='Подписка',
        title='Пробный период закончился',
        trigger='Пробный период закончился, пока действует скидка (вместо «Подписка истекла»)',
        default_template=(
            '⌛ Пробный период закончился. Скидка {discount_percent}% на первую подписку ещё действует — '
            'до {until}.'
        ),
        variables=(_DISCOUNT_PERCENT, _UNTIL),
        default_button_text='💎 Подключиться со скидкой',
    ),
    EventDef(
        key='subscription_revoked',
        group='Подписка',
        title='Доступ обновлён',
        trigger='Администратор перевыпустил пользователю ссылку и/или пароли (по галочке «уведомить»)',
        default_template=(
            '🔐 Ваш доступ к VPN обновлён. Откройте «Моя подписка», возьмите актуальную ссылку '
            'и обновите подписку в приложении.'
        ),
    ),
    EventDef(
        key='gift_redeemed',
        group='Подарки',
        title='Подарок активирован',
        trigger='Получатель активировал подарочный код (сообщение дарителю)',
        default_template='🎁 Ваш подарок активировал {who}!',
        variables=(Variable('who', '@username получателя или слово «пользователь»', '@friend'),),
    ),
    EventDef(
        key='gift_code_ready',
        group='Подарки',
        title='Подарочный код создан',
        trigger='Платёж за подарок подтверждён асинхронно — код создан',
        default_template=(
            '🎉 Оплата прошла успешно! Подарочный код создан.\n\n'
            'Отправьте эту ссылку тому, кому хотите подарить подписку:\n{link}\n\n'
            'Код действителен 30 дней.'
        ),
        variables=(Variable('link', 'Ссылка на подарок (обязательна: без неё код нельзя передать)', 'https://t.me/nrw_bot?start=gift_ABC123'),),
        required_variables=('link',),
    ),
    EventDef(
        key='balance_credited',
        group='Баланс',
        title='Баланс пополнен',
        trigger='Администратор начислил средства на баланс',
        default_template='💰 Баланс пополнен!\n\nСумма: +{amount}₽\nТекущий баланс: {balance}₽',
        variables=(
            Variable('amount', 'Начисленная сумма в рублях числом, без знака ₽', '100.00'),
            Variable('balance', 'Баланс после начисления в рублях числом', '350.00'),
        ),
    ),
    EventDef(
        key='balance_debited',
        group='Баланс',
        title='Средства списаны с баланса',
        trigger='Администратор списал средства с баланса',
        default_template='💸 Средства списаны с баланса\n\nСумма: -{amount}₽\nТекущий баланс: {balance}₽',
        variables=(
            Variable('amount', 'Списанная сумма в рублях числом (без знака)', '50.00'),
            Variable('balance', 'Баланс после списания в рублях числом', '300.00'),
        ),
    ),
    EventDef(
        key='autopay_activated',
        group='Автоплатёж',
        title='Автоплатёж подключён',
        trigger='Платёжная система подтвердила подключение автоплатежа',
        default_template='🔄 Автоплатёж подключён — подписка будет продлеваться автоматически каждый месяц.',
    ),
    EventDef(
        key='autopay_charge_failed',
        group='Автоплатёж',
        title='Не удалось списать автоплатёж',
        trigger='Очередное автосписание не прошло',
        default_template=(
            '⚠️ Не удалось списать автоплатёж — проверьте, что на карте/счёте достаточно средств.\n\n'
            'Подписка продолжает действовать до текущей даты окончания.'
        ),
    ),
    EventDef(
        key='autopay_stopped',
        group='Автоплатёж',
        title='Автоплатёж отключён',
        trigger='Банк отклонил привязку или списания подряд не проходят',
        default_template=(
            '🔕 Автоплатёж отключён (банк отклонил привязку или списания подряд не проходят).\n\n'
            'Подписку можно продлить вручную в любой момент.'
        ),
    ),
    EventDef(
        key='winback',
        group='Возврат клиентов',
        title='Возвращение клиента',
        trigger='Через 7 дней после истечения подписки, если её не продлили',
        default_template=(
            '👋 Соскучились? Ваша подписка уже некоторое время неактивна — '
            'самое время вернуться, пока для вас держим ваш профиль и настройки.'
        ),
        default_button_text='💎 Возобновить подписку',
    ),
    EventDef(
        key='abandoned_payment',
        group='Возврат клиентов',
        title='Оплата не завершена',
        trigger='Через 1 час после создания платежа, который так и не оплачен',
        default_template=(
            '💳 Похоже, оплата не завершилась. Если передумали или что-то пошло не '
            'так — можно оформить заново, это займёт минуту.'
        ),
        default_button_text='🔁 Попробовать снова',
    ),
    EventDef(
        key='welcome_nudge',
        group='Возврат клиентов',
        title='Напоминание после регистрации',
        trigger='Через 24 часа после регистрации, если пользователь ничего не купил',
        default_template=(
            '🔐 Не забыли про VPN? Пробный период уже начался — попробуйте подключиться '
            'сейчас, а когда пробный период закончится, сможете оформить подписку в один тап.'
        ),
        default_button_text='🚀 Открыть приложение',
        default_button_text_no_miniapp='🚀 Открыть меню',
    ),
)

EVENTS_BY_KEY: dict[str, EventDef] = {event.key: event for event in EVENTS}


def get_event(key: str) -> EventDef:
    try:
        return EVENTS_BY_KEY[key]
    except KeyError:
        raise UnknownEventError(key) from None
