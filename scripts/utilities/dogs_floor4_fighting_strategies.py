from collections.abc import Sequence
from typing import Final

import utilities.vision_images as vio
from utilities.card_data import Card, CardRanks, CardTypes
from utilities.fighting_strategies import IBattleStrategy, SmarterBattleStrategy
from utilities.utilities import determine_card_merge, find

ESCALIN_TEMPLATES: Final[tuple[str, ...]] = ("escalin_st", "escalin_aoe", "escalin_ult")
ROXY_TEMPLATES: Final[tuple[str, ...]] = ("roxy_st", "roxy_aoe", "roxy_ult")
NASI_TEMPLATES: Final[tuple[str, ...]] = ("nasi_heal", "nasi_stun", "nasi_ult")
THONAR_TEMPLATES: Final[tuple[str, ...]] = ("thonar_stance", "thonar_gauge", "thonar_ult")


class DogsFloor4BattleStrategy(IBattleStrategy):
    """Dogs Floor 4: per-phase hooks; default card picks from SmarterBattleStrategy."""

    turn = 0
    _phase_initialized = set()
    _last_phase_seen = None

    def _initialize_static_variables(self):
        DogsFloor4BattleStrategy.turn = 0
        DogsFloor4BattleStrategy._phase_initialized = set()
        DogsFloor4BattleStrategy._last_phase_seen = None

    def reset_run_state(self):
        """Called from DogsFloor4Fighter.run before the fight loop."""
        self._initialize_static_variables()

    def _maybe_reset(self, phase_id: str):
        if phase_id not in DogsFloor4BattleStrategy._phase_initialized:
            DogsFloor4BattleStrategy.turn = 0
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
        protected = ("lillia_aoe", "thonar_gauge")
        for i in range(1, len(hand_of_cards) - 1):
            left, right = hand_of_cards[i - 1], hand_of_cards[i + 1]
            if determine_card_merge(left, right) and (
                self._card_matches_any(left, protected) or self._card_matches_any(right, protected)
            ):
                hand_of_cards[i].card_type = CardTypes.GROUND

        # Never select Lillia AOE or Thonar gauge removal cards directly.
        for i, card in enumerate(hand_of_cards):
            if self._card_matches_any(card, protected):
                hand_of_cards[i].card_type = CardTypes.GROUND

        print("After protection card types:", [card.card_type.name for card in hand_of_cards])

        # Phase-specify logic here

        if phase == 1:
            return self.get_next_card_index_phase1(hand_of_cards, picked_cards, card_turn=card_turn)
        if phase == 2:
            return self.get_next_card_index_phase2(hand_of_cards, picked_cards, card_turn=card_turn)
        return self.get_next_card_index_phase3(hand_of_cards, picked_cards, card_turn=card_turn)

    def get_next_card_index_phase1(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_1")

        print("What turn are we in?", IBattleStrategy._fight_turn)

        # Phase 1: First turn, play a sequence of cards
        if IBattleStrategy._fight_turn == 0:
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

        print("After protection card types:", [card.card_type.name for card in hand_of_cards])
        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def get_next_card_index_phase3(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_3")
        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def _best_matching_card(self, hand_of_cards: list[Card], template_names: Sequence[str]) -> int:
        matching_ids = self._matching_card_ids(hand_of_cards, template_names)
        return matching_ids[-1] if matching_ids else -1

    def _matching_card_ids(self, hand_of_cards: list[Card], template_names: Sequence[str]) -> list[int]:
        return sorted(
            [
                idx
                for idx, card in enumerate(hand_of_cards)
                if card.card_type not in (CardTypes.DISABLED, CardTypes.NONE, CardTypes.GROUND)
                and self._card_matches_any(card, template_names)
            ],
            key=lambda idx: (hand_of_cards[idx].card_rank.value, idx),
        )

    def _card_matches_any(self, card: Card, template_names: Sequence[str]) -> bool:
        if card.card_image is None:
            return False
        return any(find(getattr(vio, template_name), card.card_image) for template_name in template_names)
