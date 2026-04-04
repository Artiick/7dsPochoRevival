import time
from collections.abc import Sequence
from copy import deepcopy
from typing import Final

import utilities.vision_images as vio
from utilities.card_data import Card, CardRanks, CardTypes
from utilities.coordinates import Coordinates
from utilities.fighting_strategies import IBattleStrategy, SmarterBattleStrategy
from utilities.utilities import (
    capture_window,
    click_im,
    determine_card_merge,
    find,
    find_and_click,
)

ESCALIN_TEMPLATES: Final[tuple[str, ...]] = ("escalin_st", "escalin_aoe", "escalin_ult")
ROXY_TEMPLATES: Final[tuple[str, ...]] = ("roxy_st", "roxy_aoe", "roxy_ult")
NASI_TEMPLATES: Final[tuple[str, ...]] = ("nasi_heal", "nasi_stun", "nasi_ult")
THONAR_TEMPLATES: Final[tuple[str, ...]] = ("thonar_stance", "thonar_gauge", "thonar_ult")
GAUGE_REMOVAL_TEMPLATES: Final[tuple[str, ...]] = ("thonar_gauge", "lillia_aoe")


class DogsFloor4BattleStrategy(IBattleStrategy):
    """Dogs Floor 4: per-phase hooks; default card picks from SmarterBattleStrategy."""

    turn = 0
    _phase_initialized = set()
    _last_phase_seen = None
    lillia_in_team = False
    roxy_in_team = False

    def _initialize_static_variables(self):
        DogsFloor4BattleStrategy._phase_initialized = set()
        DogsFloor4BattleStrategy._last_phase_seen = None

    def reset_run_state(self, *, lillia_in_team=False, roxy_in_team=False):
        """Called from DogsFloor4Fighter.run before the fight loop."""
        DogsFloor4BattleStrategy.lillia_in_team = lillia_in_team
        DogsFloor4BattleStrategy.roxy_in_team = roxy_in_team
        self._initialize_static_variables()

    def _maybe_reset(self, phase_id: str):
        if phase_id not in DogsFloor4BattleStrategy._phase_initialized:
            DogsFloor4BattleStrategy._phase_initialized.add(phase_id)

    def get_next_card_index(
        self, hand_of_cards: list[Card], picked_cards: list[Card], phase: int, card_turn=0, **kwargs
    ) -> int:
        if phase == 1 and DogsFloor4BattleStrategy._last_phase_seen != 1:
            self._initialize_static_variables()

        DogsFloor4BattleStrategy._last_phase_seen = phase

        ## Common logic -- Protect gauge removal cards at all costs!

        # If playing the card at i would bring i-1 and i+1 together and they would merge, and either
        # neighbor is Lillia AOE or Thonar gauge, mark the middle as GROUND so we do not trigger
        # that merge. (Run before blanket GROUND below so determine_card_merge still sees real types.)
        for i in range(1, len(hand_of_cards) - 1):
            left, right = hand_of_cards[i - 1], hand_of_cards[i + 1]
            if determine_card_merge(left, right) and (
                self._card_matches_any(left, GAUGE_REMOVAL_TEMPLATES)
                or self._card_matches_any(right, GAUGE_REMOVAL_TEMPLATES)
            ):
                hand_of_cards[i].card_type = CardTypes.GROUND

        # Never select Lillia AOE or Thonar gauge removal cards directly.
        for i, card in enumerate(hand_of_cards):
            if self._card_matches_any(card, GAUGE_REMOVAL_TEMPLATES):
                hand_of_cards[i].card_type = CardTypes.GROUND

        # Phase-specify logic here

        if phase == 1:
            return self.get_next_card_index_phase1(hand_of_cards, picked_cards, card_turn=card_turn)
        if phase == 2:
            return self.get_next_card_index_phase2(hand_of_cards, picked_cards, card_turn=card_turn)
        return self.get_next_card_index_phase3(hand_of_cards, picked_cards, card_turn=card_turn)

    def get_next_card_index_phase1(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_1")

        print("What turn are we in?", IBattleStrategy.fight_turn)

        # Phase 1: First turn, play a sequence of cards
        if IBattleStrategy.fight_turn == 0:
            stance_already_picked = any(
                self._card_matches_any(c, ("thonar_stance",)) for c in picked_cards if c.card_image is not None
            )
            if not stance_already_picked:
                print("Playing thonar stance")
                return self._best_matching_card(hand_of_cards, ("thonar_stance",))

            roxy_aoe_already_picked = any(
                self._card_matches_any(c, ("roxy_aoe",)) for c in picked_cards if c.card_image is not None
            )
            if not roxy_aoe_already_picked:
                best_id = self._best_matching_card(hand_of_cards, ("roxy_aoe",))
                if best_id != -1:
                    print("Playing roxy aoe")
                    return best_id

            roxy_st_already_picked = any(
                self._card_matches_any(c, ("roxy_st",)) for c in picked_cards if c.card_image is not None
            )
            if not roxy_st_already_picked:
                best_id = self._best_matching_card(hand_of_cards, ("roxy_st",))
                if best_id != -1:
                    print("Playing roxy st")
                    return best_id

            escalin_aoe_already_picked = any(
                self._card_matches_any(c, ("escalin_aoe",)) for c in picked_cards if c.card_image is not None
            )
            if not escalin_aoe_already_picked:
                print("Playing escalin aoe")
                return self._best_matching_card(hand_of_cards, ("escalin_aoe",))

        # Let's disable Nasien's stance cancel card...
        nasiens_stance_cancel_id = self._matching_card_ids(hand_of_cards, ("nasi_stun",))
        if len(nasiens_stance_cancel_id) > 0:
            print("Disabling Nasiens stance cancel card...")
            hand_of_cards[nasiens_stance_cancel_id[-1]].card_type = CardTypes.DISABLED

        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def get_next_card_index_phase2(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_2")

        nasiens_ids = self._matching_card_ids(hand_of_cards, NASI_TEMPLATES)
        has_nasiens_ult = any(self._card_matches_any(hand_of_cards[i], ("nasi_ult",)) for i in nasiens_ids)
        escalin_ids = self._matching_card_ids(hand_of_cards, ESCALIN_TEMPLATES)

        # Pick at most one Escalin card
        if any(self._card_matches_any(c, ESCALIN_TEMPLATES) for c in picked_cards if c.card_image is not None):
            for i in escalin_ids:
                print("Disabling Escalin cards")
                hand_of_cards[i].card_type = CardTypes.GROUND

        # Do not play Nasiens ult: mark it GROUND so SmarterBattleStrategy skips it (same idea as Escalin above).
        for i in nasiens_ids:
            if self._card_matches_any(hand_of_cards[i], ("nasi_ult",)):
                print("Disablnig Nasiens ult!")
                hand_of_cards[i].card_type = CardTypes.GROUND

        # If we still have no nasi_ult in hand (has_nasiens_ult was false at start of this pick) and we are on
        # the 3rd+ card of the turn, try to reshuffle: move the first non-GROUND Nasiens card one slot right.
        if card_turn >= 3 and not has_nasiens_ult:
            i = next((j for j in nasiens_ids if hand_of_cards[j].card_type != CardTypes.GROUND), None)
            if i is not None:
                print("Moving Nasiens card to get ult...")
                return [i, i + 1]
            print("Can't move a Nasiens card to get ult...")

        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def get_next_card_index_phase3(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        """Important: In phase 3, fight turns start at 1!"""
        self._maybe_reset("phase_3")

        print("We're in turn", IBattleStrategy.fight_turn)

        # First, play Nasiens ultimate if we have it
        nasiens_ult_id = self._matching_card_ids(hand_of_cards, ("nasi_ult",))
        if len(nasiens_ult_id) > 0:
            return nasiens_ult_id[-1]

        # If fight turn is <=2, just waste cards and disable Escalin cards
        if IBattleStrategy.fight_turn <= 2:
            for i in range(len(hand_of_cards)):
                if self._card_matches_any(hand_of_cards[i], ESCALIN_TEMPLATES):
                    print("Disabling Escalin cards")
                    hand_of_cards[i].card_type = CardTypes.DISABLED

            return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

        # At this point, let's see if we can remove the damage cap thingy...
        screenshot, window_location = capture_window()
        have_damage_cap = find(vio.dogs_damage_cap, screenshot, threshold=0.6)
        print("Do we see a damage cap thingy?", have_damage_cap)
        if have_damage_cap:
            remove_gauge_ids = self._matching_card_ids(hand_of_cards, GAUGE_REMOVAL_TEMPLATES, ranks=(CardRanks.GOLD,))
            if len(remove_gauge_ids) < 2:
                drag = self._best_gauge_merge_drag_indices(hand_of_cards)
                if drag is not None:
                    return drag
                print("Not enough gold cards to remove gauges...")
                return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

            # Let's play Escalin's talent and do the ult gauge removal
            if find_and_click(vio.talent_escalin, screenshot, window_location, threshold=0.6):
                print("Phase 3: activating Escalin talent!")
                time.sleep(2.5)

            if card_turn == 1:
                # Gotta click light dog!
                click_im(Coordinates.get_coordinates("light_dog"), window_location)

            if card_turn <= 1 and type(self).roxy_in_team:
                # Play Thonar's gauge cards!
                thonar_gauge_id = self._best_matching_card(hand_of_cards, ("thonar_gauge",), ranks=(CardRanks.GOLD,))
                if thonar_gauge_id != -1:
                    return thonar_gauge_id
            elif card_turn == 0 and type(self).lillia_in_team:
                # Play Lillia's gauge cards!
                lillia_aoe_id = self._best_matching_card(hand_of_cards, ("lillia_aoe",), ranks=(CardRanks.GOLD,))
                if lillia_aoe_id != -1:
                    return lillia_aoe_id

            # Re-enable Lillia/Thonar cards, we can/should play them here
            for i in range(len(hand_of_cards)):
                if self._card_matches_any(hand_of_cards[i], GAUGE_REMOVAL_TEMPLATES):
                    hand_of_cards[i].card_type = CardTypes.ATTACK

        else:
            # Damage cap not visible: go HAM — play Escalin and Roxy's cards like crazy
            escalin_ids = self._matching_card_ids(hand_of_cards, ESCALIN_TEMPLATES)
            roxy_ids = self._matching_card_ids(hand_of_cards, ROXY_TEMPLATES)
            if len(escalin_ids) > 0:
                return escalin_ids[-1]
            if len(roxy_ids) > 0:
                return roxy_ids[-1]

        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def _best_matching_card(
        self,
        hand_of_cards: list[Card],
        template_names: Sequence[str],
        *,
        ranks: Sequence[CardRanks] | None = None,
    ) -> int:
        matching_ids = self._matching_card_ids(hand_of_cards, template_names, ranks=ranks)
        return matching_ids[-1] if matching_ids else -1

    def _matching_card_ids(
        self,
        hand_of_cards: list[Card],
        template_names: Sequence[str],
        *,
        ranks: Sequence[CardRanks] | None = None,
    ) -> list[int]:
        allowed_ranks = frozenset(ranks) if ranks is not None else None
        return sorted(
            [
                idx
                for idx, card in enumerate(hand_of_cards)
                if card.card_type not in (CardTypes.DISABLED, CardTypes.NONE, CardTypes.GROUND)
                and self._card_matches_any(card, template_names)
                and (allowed_ranks is None or card.card_rank in allowed_ranks)
            ],
            key=lambda idx: (hand_of_cards[idx].card_rank.value, idx),
        )

    def _best_gauge_merge_drag_indices(self, hand_of_cards: list[Card]) -> tuple[int, int] | None:
        """Drag origin→target to merge two gauge cards; scan copy lifts GROUND so merges are visible.

        Prefer the rightmost merge: maximize target index b, then origin a (lexicographic on (b, a)).
        """
        n = len(hand_of_cards)
        if n < 2:
            return None
        scan = deepcopy(hand_of_cards)
        for card in scan:
            if self._card_matches_any(card, GAUGE_REMOVAL_TEMPLATES) and card.card_type == CardTypes.GROUND:
                card.card_type = CardTypes.ATTACK
        best: tuple[int, int] | None = None
        for a in range(n - 1):
            for b in range(a + 1, n):
                if not self._card_matches_any(scan[a], GAUGE_REMOVAL_TEMPLATES):
                    continue
                if not self._card_matches_any(scan[b], GAUGE_REMOVAL_TEMPLATES):
                    continue
                if not determine_card_merge(scan[a], scan[b]):
                    continue
                if best is None or (b, a) > (best[1], best[0]):
                    best = (a, b)
        if best is not None:
            print(f"Dragging gauge merge {best[0]} → {best[1]} (insufficient gold)")
        return best

    def _card_matches_any(self, card: Card, template_names: Sequence[str]) -> bool:
        if card.card_image is None:
            return False
        return any(find(getattr(vio, template_name), card.card_image) for template_name in template_names)
