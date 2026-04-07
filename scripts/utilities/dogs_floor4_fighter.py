"""Dogs Floor 4 fighter: first MY_TURN waits for talent_escalin (no empty-slot shortcut until then)."""

from collections.abc import Callable

import numpy as np
import utilities.vision_images as vio
from utilities.card_data import CardTypes
from utilities.dogs_fighter import DogsFighter
from utilities.dogs_floor4_fighting_strategies import DogsFloor4BattleStrategy
from utilities.general_fighter_interface import FightingStates, IFighter
from utilities.utilities import capture_window, find, get_hand_cards


class DogsFloor4Fighter(DogsFighter):
    battle_strategy: DogsFloor4BattleStrategy

    activate_phase3_escalin_talent = False
    _f4_first_my_turn_pending = True
    _fight_turn_incremented_at_turn_start = False

    def __init__(self, battle_strategy: type[DogsFloor4BattleStrategy], callback: Callable | None = None):
        super().__init__(battle_strategy=battle_strategy, callback=callback)

    def _try_enter_my_turn(self, screenshot) -> bool:
        if DogsFloor4Fighter._f4_first_my_turn_pending:
            if not find(vio.talent_escalin, screenshot, threshold=0.7):
                # Do not use empty-slot detection yet; wait until the talent button is visible.
                return False
            available = DogsFighter.count_empty_card_slots(screenshot, threshold=0.8)
            if available <= 0:
                available = 4
            if available >= 3 and self._check_disabled_hand():
                print("Our hand is fully disabled, let's restart the fight!")
                self.current_state = FightingStates.EXIT_FIGHT
                return True
            self.available_card_slots = available
            print(f"MY TURN (Floor 4 first turn: talent_escalin), selecting {available} cards...")
            self.current_state = FightingStates.MY_TURN
            DogsFloor4Fighter._f4_first_my_turn_pending = False
            return True

        entered = super()._try_enter_my_turn(screenshot)
        if entered:
            DogsFloor4Fighter._f4_first_my_turn_pending = False
        return entered

    def _maybe_increment_fight_turn_at_turn_start(self):
        """Floor 4: count turns only at turn start, and only for normal 3+/4-slot openings.

        Runs every MY_TURN loop tick before ``play_cards``; mid-turn ticks are skipped via ``picked_cards[0]``.
        Every Floor 4 phase starts from a fresh counter, and ``finish_turn`` never increments it.
        This keeps ``fight_turn`` meaning consistent across phases: it increments exactly once, at the
        start of a normal turn. If units die and opening slots stay below 3, we accept that the counter
        becomes best-effort and cleanup turns are not counted.

        Opening slot count may be nudged up from vision when it exceeds ``available_card_slots``
        (same idea as ``play_cards``).
        """
        if DogsFloor4Fighter._fight_turn_incremented_at_turn_start:
            return

        if self.picked_cards[0].card_image is not None:
            return

        screenshot, _ = capture_window()
        empty = DogsFighter.count_empty_card_slots(screenshot, threshold=0.8)
        if empty > self.available_card_slots:
            self.available_card_slots = empty

        if self.available_card_slots >= 3:
            self.battle_strategy.increment_fight_turn()
            DogsFloor4Fighter._fight_turn_incremented_at_turn_start = True

    def my_turn_state(self):
        self._identify_current_phase()
        self._maybe_increment_fight_turn_at_turn_start()
        self.play_cards()

    def _before_pick_cards(self, *, screenshot, window_location, empty_card_slots: int) -> None:
        """Floor 4 fallback: count a normal turn if slot detection stabilizes late inside ``play_cards``.

        Race we are handling:
        - ``_try_enter_my_turn`` and the early turn-start check may still see only 1 empty slot
        - the shared ``play_cards`` flow may then see 3+ empty slots moments later on the first pick
          of the same turn

        In that case, count this as a normal Floor 4 turn here using the same slot-count observation
        that will drive slot-index calculation and card selection. We still keep the overall policy
        of start-only counting and never increment at ``finish_turn``.
        """
        if DogsFloor4Fighter._fight_turn_incremented_at_turn_start:
            return
        if self.picked_cards[0].card_image is not None:
            return
        if empty_card_slots < 3:
            return
        self.battle_strategy.increment_fight_turn()
        DogsFloor4Fighter._fight_turn_incremented_at_turn_start = True

    def finish_turn(self):
        # Floor 4 turn counting is start-only for every phase. We deliberately avoid end-of-turn
        # increments so short turns (for example, 1-slot cleanup turns) do not create confusing jumps.
        DogsFloor4Fighter._fight_turn_incremented_at_turn_start = False
        self._reset_instance_variables()
        print("Finished my turn!")
        return 1

    def _check_disabled_hand(self) -> bool:
        """If we have a disabled hand (same criteria as BirdFighter)."""
        screenshot, _ = capture_window()
        house_of_cards = get_hand_cards()

        return np.all([card.card_type in [CardTypes.DISABLED, CardTypes.GROUND] for card in house_of_cards]) or find(
            vio.skill_locked, screenshot, threshold=0.6
        )

    def _identify_current_phase(self):
        prev = IFighter.current_phase
        super()._identify_current_phase()
        if prev != IFighter.current_phase:
            print(f"Entered phase {IFighter.current_phase}! Resetting the Floor 4 turn counter...")
            self.battle_strategy.reset_fight_turn()
            DogsFloor4Fighter._fight_turn_incremented_at_turn_start = False

    def run(self, floor=4, lillia_in_team=False, roxy_in_team=False):
        self.battle_strategy.reset_run_state(lillia_in_team=lillia_in_team, roxy_in_team=roxy_in_team)
        DogsFloor4Fighter._f4_first_my_turn_pending = True
        DogsFloor4Fighter._fight_turn_incremented_at_turn_start = False

        super().run(floor=floor)
