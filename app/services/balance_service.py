"""Единственная точка изменения User.balance_kopeks.

Раньше баланс менялся в Python (`user.balance_kopeks += x`) — при двух
параллельных операциях (промокод + покупка, реферальное начисление + списание)
одно изменение затиралось другим (lost update), а SELECT ... FOR UPDATE был
расставлен только в части мест и молча не работает на SQLite.

Здесь изменения делаются одним атомарным UPDATE в БД (`balance = balance + x`),
условное списание — с проверкой достаточности в самом WHERE. Вызывающий код
получает актуальное значение в переданном объекте User (refresh). Коммит —
на вызывающем.
"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import User


class InsufficientBalanceError(Exception):
    """method='balance', но db_user.balance_kopeks < цены — отдельный тип,
    чтобы cb_confirm_purchase мог показать дружелюбное "не хватает N ₽"
    вместо общего "не удалось оформить подписку"."""

    def __init__(self, missing_kopeks: int) -> None:
        self.missing_kopeks = missing_kopeks
        super().__init__(f'insufficient balance, missing {missing_kopeks} kopeks')


async def credit_balance(db: AsyncSession, user: User, amount_kopeks: int) -> None:
    """Атомарно начисляет amount_kopeks (>= 0)."""
    if amount_kopeks < 0:
        raise ValueError('credit_balance: сумма не может быть отрицательной')
    if amount_kopeks == 0:
        return
    await db.execute(
        update(User).where(User.id == user.id).values(balance_kopeks=User.balance_kopeks + amount_kopeks)
        .execution_options(synchronize_session=False)
    )
    await db.refresh(user, ['balance_kopeks'])


async def debit_balance(db: AsyncSession, user: User, amount_kopeks: int) -> None:
    """Атомарно списывает amount_kopeks ровно или бросает InsufficientBalanceError
    (баланс при этом не меняется). Проверка достаточности — в самом UPDATE, а не
    отдельным SELECT, поэтому гонка между проверкой и списанием невозможна."""
    if amount_kopeks < 0:
        raise ValueError('debit_balance: сумма не может быть отрицательной')
    if amount_kopeks == 0:
        return
    result = await db.execute(
        update(User)
        .where(User.id == user.id, User.balance_kopeks >= amount_kopeks)
        .values(balance_kopeks=User.balance_kopeks - amount_kopeks)
        .execution_options(synchronize_session=False)
    )
    await db.refresh(user, ['balance_kopeks'])
    if result.rowcount == 0:
        raise InsufficientBalanceError(amount_kopeks - user.balance_kopeks)


async def adjust_balance_clamped(db: AsyncSession, user: User, delta_kopeks: int) -> int:
    """Меняет баланс на delta (может быть отрицательной), не опуская ниже 0.
    Возвращает реально применённую дельту (после клэмпа). Строка блокируется
    FOR UPDATE, потому что нужна и старая величина (для applied), и новая."""
    locked = await db.execute(select(User.balance_kopeks).where(User.id == user.id).with_for_update())
    old_balance = locked.scalar_one()
    new_balance = max(0, old_balance + delta_kopeks)
    applied = new_balance - old_balance
    if applied != 0:
        await db.execute(
            update(User).where(User.id == user.id).values(balance_kopeks=new_balance)
            .execution_options(synchronize_session=False)
        )
    await db.refresh(user, ['balance_kopeks'])
    return applied
