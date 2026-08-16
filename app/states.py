"""FSM-состояния. Дополнять по мере реализации соответствующих флоу — не заводить
состояния 'про запас' (см. AdminStates-разрастание у Bedolaga как антипаттерн)."""

from aiogram.fsm.state import State, StatesGroup


class RegistrationStates(StatesGroup):
    choosing_language = State()
    accepting_rules = State()


class PurchaseStates(StatesGroup):
    choosing_period = State()
    choosing_payment_method = State()
    confirming = State()


class PromoCodeStates(StatesGroup):
    entering_code = State()


class GiftStates(StatesGroup):
    choosing_period = State()
    choosing_payment_method = State()


class SupportStates(StatesGroup):
    writing_message = State()


class AdminTariffStates(StatesGroup):
    entering_name = State()
    entering_prices = State()


class AdminPromoCodeStates(StatesGroup):
    entering_code = State()
    entering_type = State()
    entering_value = State()
    entering_max_activations = State()


class AdminBroadcastStates(StatesGroup):
    entering_text = State()
    confirming = State()


class AdminUserStates(StatesGroup):
    awaiting_telegram_id = State()


class AdminEmojiStates(StatesGroup):
    awaiting_message = State()
