from aiogram.fsm.state import State, StatesGroup


class FaceProtocolStates(StatesGroup):
    waiting_for_consent = State()
    waiting_for_name = State()
    waiting_for_age = State()
    waiting_for_photo = State()
    waiting_for_problems = State()
