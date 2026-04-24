import time
from typing import Callable

import cv2
import numpy as np
import utilities.vision_images as vio
from utilities.card_data import Card
from utilities.coordinates import Coordinates
from utilities.fighting_strategies import IBattleStrategy
from utilities.general_fighter_interface import FightingStates, IFighter
from utilities.utilities import (
    capture_window,
    click_im,
    draw_rectangles,
    find,
    find_and_click,
    get_card_slot_region_image,
)
from utilities.vision import Vision


class DogsFighter(IFighter):
    # Keep track of what floor has been defeated
    floor_defeated = None

    # Keep track of the current floor
    current_floor = 1

    # Subclasses (e.g. Floor 4) may set False to skip auto-clicking Escalin talent on phase 3 entry.
    activate_phase3_escalin_talent = True
    TARGET_CONFIRM_RETRIES = 3
    TARGET_CONFIRM_TIMEOUT_SECONDS = 0.8
    TARGET_CONFIRM_POLL_SECONDS = 0.08

    def __init__(self, battle_strategy: IBattleStrategy, callback: Callable | None = None):
        super().__init__(battle_strategy=battle_strategy, callback=callback)

        # Reset the current phase to -1
        IFighter.current_phase = -1
        self.target_selected_phase = None

    def fighting_state(self):

        screenshot, window_location = capture_window()

        # In case we've been lazy and it's the first time we're doing Demonic Beast this week...
        find_and_click(
            vio.weekly_mission,
            screenshot,
            window_location,
            point_coordinates=Coordinates.get_coordinates("lazy_weekly_bird_mission"),
        )
        find_and_click(vio.daily_quest_info, screenshot, window_location)

        # To skip quickly to the rewards when the fight is done
        find_and_click(vio.creature_destroyed, screenshot, window_location)

        if find(vio.defeat, screenshot) or find(vio.close, screenshot):
            # I may have lost though...
            print("I lost! :(")
            self.current_state = FightingStates.DEFEAT

        elif find(vio.db_victory, screenshot, threshold=0.7):
            # Fight is complete
            print("Fighting complete! Is it true? Double check...")
            self.current_state = FightingStates.FIGHTING_COMPLETE

        elif self._try_enter_my_turn(screenshot):
            pass

    def _check_disabled_hand(self) -> bool:
        """Subclasses (e.g. DogsFloor4Fighter) may override to match bird-style full-hand disable detection."""
        return False

    def _try_enter_my_turn(self, screenshot) -> bool:
        """If empty card slots are visible, enter MY_TURN. Subclasses may override (e.g. Floor 4 first turn)."""
        available_card_slots = DogsFighter.count_empty_card_slots(screenshot, threshold=0.8)
        if available_card_slots <= 0:
            return False
        if available_card_slots >= 3 and self._check_disabled_hand():
            print("Our hand is fully disabled, let's restart the fight!")
            self.current_state = FightingStates.EXIT_FIGHT
            return True
        self.available_card_slots = available_card_slots
        print(f"MY TURN, selecting {available_card_slots} cards...")
        self.current_state = FightingStates.MY_TURN
        return True

    @staticmethod
    def count_empty_card_slots(screenshot, threshold=0.6, debug=False):
        """Count how many empty card slots are there for DOGS"""
        card_slot_image = get_card_slot_region_image(screenshot)
        rectangles = []
        for i in range(1, 25):
            vio_image: Vision = getattr(vio, f"empty_slot_{i}", None)
            if vio_image is not None and vio_image.needle_img is not None:
                temp_rectangles, _ = vio_image.find_all_rectangles(
                    card_slot_image, threshold=threshold, method=cv2.TM_CCOEFF_NORMED
                )
                rectangles.extend(temp_rectangles)

        # groupThreshold=1 means each cluster needs at least two detections; otherwise
        # OpenCV drops the whole cluster. Our slot hits are usually one rect per slot
        # (non-overlapping), so we duplicate the list once to supply the second vote.
        doubled = rectangles + rectangles if rectangles else []
        grouped_rectangles, _ = cv2.groupRectangles(doubled, groupThreshold=1, eps=0.5)
        if debug and len(grouped_rectangles):
            print(f"We have {len(grouped_rectangles)} empty slots.")
            # rectangles_fig = draw_rectangles(screenshot, np.array(rectangles), line_color=(0, 0, 255))
            translated_rectangles = np.array(
                [
                    [
                        r[0] + Coordinates.get_coordinates("card_slots_region")[0],
                        r[1] + Coordinates.get_coordinates("card_slots_region")[1],
                        r[2],
                        r[3],
                    ]
                    for r in grouped_rectangles
                ]
            )
            rectangles_fig = draw_rectangles(screenshot, translated_rectangles)
            cv2.imshow("rectangles", rectangles_fig)
            cv2.waitKey(0)
            cv2.destroyAllWindows()
        if len(grouped_rectangles) > 0:
            print(f"Found {len(grouped_rectangles)} empty card slots.")
        return 4 if find(vio.skill_locked, screenshot, threshold=0.6) else len(grouped_rectangles)

    def my_turn_state(self):
        """State in which the 4 cards will be picked and clicked. Overrides the parent method."""

        # Before playing cards, first:
        # 1. Read the phase we're in
        # 2. Make sure to click on the correct dog (right/left) depending on the phase
        # empty_card_slots = self.count_empty_card_slots(screenshot)
        if not self._identify_current_phase():
            return

        # Then play the cards
        self.play_cards()

    def _identify_current_phase(self):  # sourcery skip: extract-duplicate-method
        """Identify DB phase"""
        screenshot, window_location = capture_window()
        if find(vio.phase_1, screenshot, threshold=0.8) and IFighter.current_phase != 1:
            if (available_card_slots := DogsFighter.count_empty_card_slots(screenshot, threshold=0.8)) > 1:
                IFighter.current_phase = 1
                self.target_selected_phase = None
        elif find(vio.phase_2, screenshot, threshold=0.8) and IFighter.current_phase != 2:
            IFighter.current_phase = 2
            self.target_selected_phase = None
        elif find(vio.phase_3_dogs, screenshot, threshold=0.8) and IFighter.current_phase != 3:
            IFighter.current_phase = 3
            self.target_selected_phase = None

        if IFighter.current_phase == 1 and self.target_selected_phase != 1:
            if not self._ensure_dogs_target_selected("right", "light_dog", window_location):
                return False
            self.target_selected_phase = 1
        elif IFighter.current_phase in {2, 3} and self.target_selected_phase != IFighter.current_phase:
            if not self._ensure_dogs_target_selected("left", "dark_dog", window_location):
                return False
            self.target_selected_phase = IFighter.current_phase
            if IFighter.current_phase == 3 and type(self).activate_phase3_escalin_talent:
                screenshot, window_location = capture_window()
                if find_and_click(vio.talent_escalin, screenshot, window_location, threshold=0.6):
                    print("Phase 3 entry: activating talent_escalin")
                    time.sleep(2.5)

        return True

    @staticmethod
    def _get_dogs_selected_target_sides(screenshot) -> set[str]:
        selected_sides = set()
        if find(vio.dogs_left_target_sel, screenshot, threshold=0.8):
            selected_sides.add("left")
        if find(vio.dogs_right_target_sel, screenshot, threshold=0.8) or find(
            vio.dogs_right_target_sel2,
            screenshot,
            threshold=0.8,
        ):
            selected_sides.add("right")
        return selected_sides

    def _wait_for_dogs_target_selection(self, target_side: str) -> bool:
        deadline = time.time() + self.TARGET_CONFIRM_TIMEOUT_SECONDS
        while time.time() < deadline:
            screenshot, _ = capture_window()
            if target_side in self._get_dogs_selected_target_sides(screenshot):
                return True
            time.sleep(self.TARGET_CONFIRM_POLL_SECONDS)
        return False

    def _ensure_dogs_target_selected(self, target_side: str, coordinate_key: str, window_location) -> bool:
        screenshot, _ = capture_window()
        if target_side in self._get_dogs_selected_target_sides(screenshot):
            print(f"Dogs target verification: {target_side} dog is already selected.")
            return True

        for attempt in range(1, self.TARGET_CONFIRM_RETRIES + 1):
            print(
                f"Dogs targeting: clicking the {target_side} dog for phase {IFighter.current_phase} "
                f"(attempt {attempt}/{self.TARGET_CONFIRM_RETRIES})."
            )
            click_im(Coordinates.get_coordinates(coordinate_key), window_location)
            if self._wait_for_dogs_target_selection(target_side):
                print(f"Dogs target verification: confirmed {target_side} dog selection.")
                return True

        print(
            f"Dogs target verification failed: could not confirm {target_side} dog selection "
            "after repeated clicks. Waiting for the next loop instead of firing cards blind."
        )
        return False

    def fight_complete_state(self):

        screenshot, window_location = capture_window()

        find_and_click(vio.daily_quest_info, screenshot, window_location)

        if find(vio.guaranteed_reward, screenshot):
            DogsFighter.floor_defeated = 3

        # Click on the OK button to end the fight
        find_and_click(vio.ok_main_button, screenshot, window_location)

        # Only consider the fight complete if we see the loading screen, in case we need to click OK multiple times
        if find(vio.db_loading_screen, screenshot):
            self.complete_callback(victory=True, phase=IFighter.current_phase)
            self.exit_thread = True
            # Reset the defeated floor
            DogsFighter.floor_defeated = None

    def defeat_state(self):
        """We've lost the battle..."""
        screenshot, window_location = capture_window()

        find_and_click(vio.daily_quest_info, screenshot, window_location)

        find_and_click(vio.ok_main_button, screenshot, window_location)

        # In case we see a "close" button
        find_and_click(vio.close, screenshot, window_location)

        if find(vio.db_loading_screen, screenshot):
            # We're going back to the main bird menu, let's end this thread
            self.complete_callback(victory=False, phase=IFighter.current_phase)
            self.exit_thread = True
            # Reset the current phase
            IFighter.current_phase = None

    def exit_fight_state(self):
        """Manually finish the fight when the hand is fully disabled (same flow as BirdFighter)."""
        self._run_manual_forfeit_flow()

    @IFighter.run_wrapper
    def run(self, floor=1):

        print(f"Fighting very hard on floor {floor}...")
        IFighter.current_floor = floor

        while True:

            if self.current_state == FightingStates.FIGHTING:
                self.fighting_state()

            elif self.current_state == FightingStates.MY_TURN:
                self.my_turn_state()

            elif self.current_state == FightingStates.FIGHTING_COMPLETE:
                self.fight_complete_state()

            elif self.current_state == FightingStates.DEFEAT:
                self.defeat_state()

            elif self.current_state == FightingStates.EXIT_FIGHT:
                self.exit_fight_state()

            if self.exit_thread:
                print("Closing Fighter thread!")
                return

            time.sleep(0.5)
