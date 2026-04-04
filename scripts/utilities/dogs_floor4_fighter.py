"""Dogs Floor 4 fighter: first MY_TURN uses talent_escalin; then base empty-slot detection."""

from collections.abc import Callable

import utilities.vision_images as vio
from utilities.dogs_fighter import DogsFighter
from utilities.dogs_floor4_fighting_strategies import DogsFloor4BattleStrategy
from utilities.general_fighter_interface import FightingStates
from utilities.utilities import find


class DogsFloor4Fighter(DogsFighter):
    battle_strategy: DogsFloor4BattleStrategy

    _f4_first_my_turn_pending = True

    def __init__(self, battle_strategy: type[DogsFloor4BattleStrategy], callback: Callable | None = None):
        super().__init__(battle_strategy=battle_strategy, callback=callback)

    def _try_enter_my_turn(self, screenshot) -> bool:
        if DogsFloor4Fighter._f4_first_my_turn_pending and find(vio.talent_escalin, screenshot, threshold=0.7):
            available = DogsFighter.count_empty_card_slots(screenshot, threshold=0.8)
            if available <= 0:
                available = 4
            self.available_card_slots = available
            print(f"MY TURN (Floor 4 first turn: talent_escalin), selecting {available} cards...")
            self.current_state = FightingStates.MY_TURN
            DogsFloor4Fighter._f4_first_my_turn_pending = False
            return True

        entered = super()._try_enter_my_turn(screenshot)
        if entered:
            DogsFloor4Fighter._f4_first_my_turn_pending = False
        return entered

    def run(self, floor=4):
        self.battle_strategy.reset_run_state()
        DogsFloor4Fighter._f4_first_my_turn_pending = True

        super().run(floor=floor)
