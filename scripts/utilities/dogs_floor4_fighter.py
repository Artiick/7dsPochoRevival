"""Minimal Dogs Floor 4 fighter: hooks for DogsFloor4BattleStrategy (talent, targeting, turn callback, reset)."""

import time
from numbers import Integral

from utilities.card_data import Card
from utilities.coordinates import Coordinates
from utilities.dogs_fighter import DogsFighter
from utilities.general_fighter_interface import IFighter
from utilities.utilities import click_im


class DogsFloor4Fighter(DogsFighter):
    def finish_turn(self):
        if hasattr(self.battle_strategy, "on_player_turn_completed"):
            self.battle_strategy.on_player_turn_completed(IFighter.current_phase)
        return super().finish_turn()

    @staticmethod
    def _phase3_target_coordinate_key(target_side: str) -> str:
        return "dark_dog" if target_side == "left" else "light_dog"

    def _activate_phase3_talent(self, window_location):
        print("Activating phase 3 talent (Escalin).")
        click_im(Coordinates.get_coordinates("talent"), window_location)
        time.sleep(2.5)

    def _play_card(
        self,
        list_of_cards,
        index,
        window_location,
        screenshot=None,
    ):
        if isinstance(index, Integral) and index == -1:
            return super()._play_card(
                list_of_cards, index=index, window_location=window_location, screenshot=screenshot
            )

        target_side = None
        expected_auto_merges = 0
        strategy_cls = type(self.battle_strategy)

        if IFighter.current_phase == 2 and isinstance(index, Integral):
            use_talent = getattr(strategy_cls, "phase2_use_talent_before_next_play", False)
            if use_talent:
                self._activate_phase3_talent(window_location)
                time.sleep(1.0)
                strategy_cls.phase2_use_talent_before_next_play = False

        if IFighter.current_phase == 3 and isinstance(index, Integral):
            use_talent = getattr(strategy_cls, "phase3_use_talent_before_next_play", False)
            target_side = getattr(strategy_cls, "phase3_next_target_side", None)

            if use_talent:
                self._activate_phase3_talent(window_location)
                if hasattr(self.battle_strategy, "register_phase3_talent_use"):
                    self.battle_strategy.register_phase3_talent_use()
                strategy_cls.phase3_use_talent_before_next_play = False

            if target_side in {"left", "right"}:
                click_im(Coordinates.get_coordinates(self._phase3_target_coordinate_key(target_side)), window_location)
                time.sleep(0.12)
                strategy_cls.phase3_next_target_side = None

        if isinstance(index, Integral) and hasattr(self.battle_strategy, "estimate_auto_merge_count_after_play"):
            expected_auto_merges = self.battle_strategy.estimate_auto_merge_count_after_play(list_of_cards, index)

        played_card = super()._play_card(
            list_of_cards, index=index, window_location=window_location, screenshot=screenshot
        )

        if hasattr(self.battle_strategy, "register_confirmed_action"):
            self.battle_strategy.register_confirmed_action(list_of_cards, index, played_card)

        if (
            IFighter.current_phase == 3
            and isinstance(index, Integral)
            and hasattr(self.battle_strategy, "register_phase3_card_play")
        ):
            self.battle_strategy.register_phase3_card_play(played_card, target_side=target_side)

        if expected_auto_merges > 0:
            merge_wait = 0.55 + (expected_auto_merges - 1) * 0.35
            time.sleep(merge_wait)

        return played_card

    def run(self, floor=4):
        if hasattr(self.battle_strategy, "reset_run_state"):
            self.battle_strategy.reset_run_state()
        super().run(floor=floor)
