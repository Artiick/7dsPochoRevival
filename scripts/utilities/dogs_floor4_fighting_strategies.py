import time
from collections.abc import Sequence
from copy import deepcopy
from typing import Final

import numpy as np
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

    removed_damage_cap = False

    def _initialize_static_variables(self):
        DogsFloor4BattleStrategy._phase_initialized = set()
        DogsFloor4BattleStrategy._last_phase_seen = None
        DogsFloor4BattleStrategy.removed_damage_cap = False

    def reset_run_state(self, *, lillia_in_team=False, roxy_in_team=False):
        """Called from DogsFloor4Fighter.run before the fight loop."""
        print("Resetting run state with Lillia in team:", lillia_in_team, "and Roxy in team:", roxy_in_team)
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

        ## Common logic -- Protect gauge removal cards at all costs (non-Lillia teams only)!

        if not type(self).lillia_in_team:
            # Mark Thonar gauge cards GROUND so Smarter skips them unless phase logic explicitly plays them.
            ids = [i for i, c in enumerate(hand_of_cards) if self._card_matches_any(c, ("thonar_gauge",))]
            if ids:
                n_gold = sum(1 for i in ids if hand_of_cards[i].card_rank == CardRanks.GOLD)
                if n_gold <= 1:
                    # Single (or no) gold: reserve every Thonar gauge — nothing safe to leave playable.
                    to_ground = ids
                else:
                    # Two+ golds: reserve only the two best ranks if that pair is both gold; else reserve all.
                    top2 = sorted(ids, key=lambda j: (hand_of_cards[j].card_rank.value, j), reverse=True)[:2]
                    to_ground = top2 if all(hand_of_cards[j].card_rank == CardRanks.GOLD for j in top2) else ids
                for i in to_ground:
                    hand_of_cards[i].card_type = CardTypes.GROUND

        else:
            # Save one Lillia AOE card
            lillia_aoe_ids = self._matching_card_ids(hand_of_cards, ("lillia_aoe",))
            if len(lillia_aoe_ids) > 0:
                hand_of_cards[lillia_aoe_ids[-1]].card_type = CardTypes.GROUND

        # Phase-specify logic here

        if phase == 1:
            return self.get_next_card_index_phase1(hand_of_cards, picked_cards, card_turn=card_turn)
        if phase == 2:
            return self.get_next_card_index_phase2(hand_of_cards, picked_cards, card_turn=card_turn)
        return self.get_next_card_index_phase3(hand_of_cards, picked_cards, card_turn=card_turn)

    def get_next_card_index_phase1(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_1")

        # Phase 1: First turn, play a sequence of cards
        if IBattleStrategy.fight_turn == 0:
            stance_already_picked = bool(self._matching_card_ids(picked_cards, ("thonar_stance",)))
            if not stance_already_picked:
                print("Playing thonar stance")
                return self._best_matching_card(hand_of_cards, ("thonar_stance",))

            thonar_gauge_id = self._best_matching_card(hand_of_cards, ("thonar_gauge",))
            if type(self).lillia_in_team and thonar_gauge_id != -1:
                print("Playing thonar gauge")
                return thonar_gauge_id

            lillia_st_already_picked = bool(self._matching_card_ids(picked_cards, ("lillia_st",)))
            if not lillia_st_already_picked:
                best_id = self._best_matching_card(hand_of_cards, ("lillia_st",))
                if best_id != -1:
                    print("Playing lillia st")
                    return best_id

            roxy_aoe_already_picked = bool(self._matching_card_ids(picked_cards, ("roxy_aoe",)))
            if not roxy_aoe_already_picked:
                best_id = self._best_matching_card(hand_of_cards, ("roxy_aoe",))
                if best_id != -1:
                    print("Playing roxy aoe")
                    return best_id

            roxy_st_already_picked = bool(self._matching_card_ids(picked_cards, ("roxy_st",)))
            if not roxy_st_already_picked:
                best_id = self._best_matching_card(hand_of_cards, ("roxy_st",))
                if best_id != -1:
                    print("Playing roxy st")
                    return best_id

            escalin_aoe_already_picked = bool(self._matching_card_ids(picked_cards, ("escalin_aoe",)))
            if not escalin_aoe_already_picked and card_turn == 3:
                print("Playing escalin aoe")
                return self._best_matching_card(hand_of_cards, ("escalin_aoe",))

        # Let's disable Nasien's stance cancel card...
        nasiens_stance_cancel_id = self._matching_card_ids(hand_of_cards, ("nasi_stun",))
        if len(nasiens_stance_cancel_id) > 0 and IBattleStrategy.fight_turn == 1:
            print("Disabling Nasiens stance cancel card...")
            hand_of_cards[nasiens_stance_cancel_id[-1]].card_type = CardTypes.DISABLED

        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def get_next_card_index_phase2(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_2")

        nasiens_ids = self._matching_card_ids(hand_of_cards, NASI_TEMPLATES)
        has_nasiens_ult = any(self._card_matches_any(hand_of_cards[i], ("nasi_ult",)) for i in nasiens_ids)
        escalin_ids = self._matching_card_ids(hand_of_cards, ESCALIN_TEMPLATES)

        nas_stuns = self._matching_card_ids(hand_of_cards, ("nasi_stun",), ranks=(CardRanks.SILVER, CardRanks.GOLD))
        played_nas_stuns = bool(
            self._matching_card_ids(picked_cards, ("nasi_stun",), ranks=(CardRanks.SILVER, CardRanks.GOLD))
        )
        # If we still have no nasi_ult in hand (has_nasiens_ult was false at start of this pick) and we are on
        # the 3rd+ card of the turn, try to reshuffle: move the first non-GROUND Nasiens card one slot right.
        if card_turn == 0 and not has_nasiens_ult and len(nasiens_ids) > 0:
            print("Moving Nasiens card to get ult...")
            return [nasiens_ids[-1], nasiens_ids[-1] + 1]

        if len(nas_stuns) > 0 and not played_nas_stuns:
            return nas_stuns[-1]

        # Pick at most one Escalin card -- Only in non-Lillia teams, because Lillia's damage is a**
        if not type(self).lillia_in_team and bool(self._matching_card_ids(picked_cards, ESCALIN_TEMPLATES)):
            for i in escalin_ids:
                print("Disabling Escalin cards")
                hand_of_cards[i].card_type = CardTypes.DISABLED

        # Do not play Nasiens ult: mark it GROUND so SmarterBattleStrategy skips it (same idea as Escalin above).
        for i in nasiens_ids:
            if self._card_matches_any(hand_of_cards[i], ("nasi_ult",)):
                print("Disablnig Nasiens ult!")
                hand_of_cards[i].card_type = CardTypes.DISABLED

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

            drag = self._best_gauge_merge_drag_indices(hand_of_cards)
            if drag is not None:
                return drag

            return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

        # At this point, let's see if we can remove the damage cap thingy...
        screenshot, window_location = capture_window()
        # Safety net:
        has_damage_cap = not DogsFloor4BattleStrategy.removed_damage_cap or find(vio.dogs_damage_cap, screenshot)
        DogsFloor4BattleStrategy.removed_damage_cap = not has_damage_cap
        if has_damage_cap:
            # First, check if we've played enough
            played_thonar_ids = self._tr(picked_cards, ("thonar_gauge",), CardRanks.GOLD)
            played_lillia_ids = self._tr(picked_cards, ("lillia_aoe",), CardRanks.GOLD)
            if played_thonar_ids.size >= 2 or played_lillia_ids.size >= 1:
                DogsFloor4BattleStrategy.removed_damage_cap = True
                return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

            thonar_gauge_ids = self._tr(hand_of_cards, ("thonar_gauge",), CardRanks.GOLD)
            lillia_aoe_ids = self._tr(hand_of_cards, ("lillia_aoe",), CardRanks.GOLD)
            print("These many thonar and lillia cards available:", thonar_gauge_ids.size, lillia_aoe_ids.size)

            # Count GOLD thonar_gauge in hand plus already played this turn (picked_cards).
            if lillia_aoe_ids.size == 0 and (played_thonar_ids.size + thonar_gauge_ids.size) < 2:
                drag = self._best_gauge_merge_drag_indices(hand_of_cards)
                if drag is not None:
                    return drag
                print("Not enough gold cards to remove gauges...")
                return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

            # Let's play Escalin's talent and do the ult gauge removal
            if find_and_click(vio.talent_escalin, screenshot, window_location, threshold=0.6):
                print("Phase 3: activating Escalin talent!")
                time.sleep(2.5)

            if played_thonar_ids.size == 1:
                # Gotta click light dog after we've played the first remove gauge card
                print("Clicking light dog after playing the first remove gauge card!")
                click_im(Coordinates.get_coordinates("light_dog"), window_location)
                time.sleep(1)

            if lillia_aoe_ids.size:
                DogsFloor4BattleStrategy.removed_damage_cap = True
                print("Playing a GOLD Lillia card!")
                return int(lillia_aoe_ids[-1])

            if played_thonar_ids.size <= 1:
                # Play Thonar's gauge cards!
                thonar_gauge_id = int(thonar_gauge_ids[-1]) if thonar_gauge_ids.size else -1
                if thonar_gauge_id != -1:
                    print("Playing a GOLD Thonar card!")
                    if played_thonar_ids.size == 1:
                        DogsFloor4BattleStrategy.removed_damage_cap = True
                    return thonar_gauge_id

            # Re-enable Lillia/Thonar cards, we can/should play them here -- Maybe not needed, but just in case
            for i in range(len(hand_of_cards)):
                if self._card_matches_any(hand_of_cards[i], GAUGE_REMOVAL_TEMPLATES):
                    hand_of_cards[i].card_type = CardTypes.ATTACK

        else:
            # Damage cap not visible: go HAM — play Escalin and Roxy's cards like crazy
            print("No more damage cap, let's go HAM!")
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

    def _tr(self, cards: list[Card], templates: Sequence[str], rank: CardRanks) -> np.ndarray:
        """Indices where template matches and rank matches (ignores GROUND — for gauge bookkeeping)."""
        r = np.array([c.card_rank.value for c in cards])
        return np.where(np.array([self._card_matches_any(c, templates) for c in cards]) & (r == rank.value))[0]

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
