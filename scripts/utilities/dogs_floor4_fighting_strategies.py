import time
from collections.abc import Sequence
from copy import copy, deepcopy
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
# Single-target gauge templates (thonar_gauge, cusack_gauge): same cap-removal / merge / GROUND rules as each other; Lillia AOE separate.
ST_GAUGE_TEMPLATES: Final[tuple[str, ...]] = ("thonar_gauge", "cusack_gauge")
GAUGE_REMOVAL_TEMPLATES: Final[tuple[str, ...]] = (*ST_GAUGE_TEMPLATES, "lillia_aoe")


class DogsFloor4BattleStrategy(IBattleStrategy):
    """Dogs Floor 4: per-phase hooks; default card picks from SmarterBattleStrategy."""

    turn = 0
    _phase_initialized = set()
    _last_phase_seen = None
    lillia_in_team = False
    roxy_in_team = False
    taunt_removed = False

    removed_damage_cap = False
    # Minimum fight_turn index where Escalin/Roxy HAM is allowed; block while fight_turn < this (-1 = unset).
    _defer_ham_cards_until_after_fight_turn = -1

    def _initialize_static_variables(self):
        DogsFloor4BattleStrategy._phase_initialized = set()
        DogsFloor4BattleStrategy._last_phase_seen = None
        DogsFloor4BattleStrategy.removed_damage_cap = False
        DogsFloor4BattleStrategy._defer_ham_cards_until_after_fight_turn = -1
        DogsFloor4BattleStrategy.taunt_removed = False

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
            # Mark ST gauge cards GROUND so Smarter skips them unless phase logic explicitly plays them.
            ids = [i for i, c in enumerate(hand_of_cards) if self._card_matches_any(c, ST_GAUGE_TEMPLATES)]
            if ids:
                n_gold = sum(1 for i in ids if hand_of_cards[i].card_rank == CardRanks.GOLD)
                if n_gold <= 1:
                    # Single (or no) gold: reserve every ST gauge — nothing safe to leave playable.
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

        # # Disable any playable card between two ST gauges if playing it would merge those neighbors.
        # for i in range(1, len(hand_of_cards) - 1):
        #     mid = hand_of_cards[i]
        #     if mid.card_type in (CardTypes.GROUND, CardTypes.DISABLED, CardTypes.NONE):
        #         continue
        #     L, R = hand_of_cards[i - 1], hand_of_cards[i + 1]
        #     if not (
        #         self._card_matches_any(L, ST_GAUGE_TEMPLATES)
        #         and self._card_matches_any(R, ST_GAUGE_TEMPLATES)
        #     ):
        #         continue
        #     a, b = copy(L), copy(R)
        #     for c in (a, b):
        #         if c.card_type == CardTypes.GROUND:
        #             c.card_type = CardTypes.ATTACK
        #     if determine_card_merge(a, b):
        #         mid.card_type = CardTypes.DISABLED

        # Phase-specify logic here

        if phase == 1:
            return self.get_next_card_index_phase1(hand_of_cards, picked_cards, card_turn=card_turn)
        if phase == 2:
            return self.get_next_card_index_phase2(hand_of_cards, picked_cards, card_turn=card_turn)
        return self.get_next_card_index_phase3(hand_of_cards, picked_cards, card_turn=card_turn)

    def get_next_card_index_phase1(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_1")

        # Let's start with Escalin's talent
        screenshot, window_location = capture_window()
        if find_and_click(vio.talent_escalin, screenshot, window_location, threshold=0.6):
            print("Phase 3: activating Escalin talent!")
            time.sleep(2.5)

        # Phase 1: First turn, play a sequence of cards
        if IBattleStrategy.fight_turn == 0:

            stance_already_picked = bool(self._matching_card_ids(picked_cards, ("thonar_stance",)))
            if not stance_already_picked:
                print("Playing thonar stance")
                return self._best_matching_card(hand_of_cards, ("thonar_stance",))

            st_gauge_id = self._best_matching_card(hand_of_cards, ST_GAUGE_TEMPLATES)
            if type(self).lillia_in_team and st_gauge_id != -1:
                print("Playing gold ST gauge")
                return st_gauge_id

            cusack_cleave_id = self._best_matching_card(hand_of_cards, ("cusack_cleave",))
            if cusack_cleave_id != -1:
                print("Playing cusack cleave")
                return cusack_cleave_id

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

        # fight_turn 1: with two Nasi stuns, burn filler (no Escalin/Roxy/stun); else legacy single-stun tuck.
        if IBattleStrategy.fight_turn == 1:
            nasiens_stance_cancel_id = self._matching_card_ids(hand_of_cards, ("nasi_stun",))
            if len(nasiens_stance_cancel_id) >= 2:
                print("Phase 1: two Nasi stuns — disabling Escalin, Roxy, and up to two stuns for this pick.")
                for group in (
                    self._matching_card_ids(hand_of_cards, ESCALIN_TEMPLATES),
                    self._matching_card_ids(hand_of_cards, ROXY_TEMPLATES),
                ):
                    for i in group:
                        hand_of_cards[i].card_type = CardTypes.DISABLED
                for i in nasiens_stance_cancel_id[-2:]:
                    # Disabling 2 Nasiens cards
                    hand_of_cards[i].card_type = CardTypes.DISABLED
            elif nasiens_stance_cancel_id:
                print("Disabling Nasiens stance cancel card...")
                hand_of_cards[nasiens_stance_cancel_id[-1]].card_type = CardTypes.DISABLED

        if IBattleStrategy.fight_turn == 3 and card_turn == 0:
            nas_open = self._matching_card_ids(hand_of_cards, ("nasi_stun",), ranks=(CardRanks.SILVER, CardRanks.GOLD))
            if nas_open:
                return nas_open[-1]

        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def get_next_card_index_phase2(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_2")

        nasiens_ids = self._matching_card_ids(hand_of_cards, NASI_TEMPLATES)
        has_nasiens_ult = any(self._card_matches_any(hand_of_cards[i], ("nasi_ult",)) for i in nasiens_ids)

        # If we still have no nasi_ult in hand (has_nasiens_ult was false at start of this pick) and we are on
        # the 3rd+ card of the turn, try to reshuffle: move the first non-GROUND Nasiens card one slot right.
        if card_turn == 0 and not has_nasiens_ult and len(nasiens_ids) > 0:
            print("Moving Nasiens card to get ult...")
            return [nasiens_ids[-1], nasiens_ids[-1] + 1]

        # On even turns, we have to play a stance cancel
        if IBattleStrategy.fight_turn % 2 == 0:
            for i, card in enumerate(hand_of_cards):
                if card.card_type == CardTypes.ATTACK_DEBUFF:
                    hand_of_cards[i].card_type = CardTypes.GROUND
                    return i

        # Do not play Nasiens ult: mark it GROUND so SmarterBattleStrategy skips it (same idea as Escalin above).
        for i in nasiens_ids:
            if self._card_matches_any(hand_of_cards[i], ("nasi_ult",)):
                print("Disablnig Nasiens ult!")
                hand_of_cards[i].card_type = CardTypes.GROUND

        # Phase 2: Tuck one SILVER/GOLD roxy_st so Smarter skips it (same pattern as _smarter_phase3).
        roxy_st_hi = (CardRanks.SILVER, CardRanks.GOLD)
        if type(self).roxy_in_team:
            roxy_st_saveable = self._tr(hand_of_cards, ("roxy_st",), roxy_st_hi)
            if roxy_st_saveable.size > 0:
                hand_of_cards[int(roxy_st_saveable[-1])].card_type = CardTypes.GROUND
        # All-GROUND confuses downstream; unstick one SILVER/GOLD roxy_st to DISABLED if needed.
        if hand_of_cards and all(c.card_type == CardTypes.GROUND for c in hand_of_cards):
            rx = self._tr(hand_of_cards, ("roxy_st",), roxy_st_hi)
            if rx.size > 0:
                hand_of_cards[int(rx[-1])].card_type = CardTypes.DISABLED

        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def get_next_card_index_phase3(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        """Important: In phase 3, fight turns start at 1!"""
        self._maybe_reset("phase_3")

        print(f"Phase 3: fight turn {IBattleStrategy.fight_turn}")
        if IBattleStrategy.fight_turn % 2 == 0 and card_turn == 0:
            print("Dog is putting up a taunt...")
            DogsFloor4BattleStrategy.taunt_removed = False

        # Let's set to GROUND all ST gauge cards
        st_gauge_ids = [i for i, card in enumerate(hand_of_cards) if self._card_matches_any(card, ST_GAUGE_TEMPLATES)]
        for i in st_gauge_ids:
            hand_of_cards[i].card_type = CardTypes.GROUND

        # Pre-cap Roxy: BRONZE roxy_st merge when hand has no SILVER/GOLD roxy_st.
        # SILVER/GOLD tuck for Smarter is in _smarter_phase3.
        if (
            type(self).roxy_in_team
            and not DogsFloor4BattleStrategy.removed_damage_cap
            and not DogsFloor4BattleStrategy.taunt_removed
        ):
            roxy_st_ids = self._tr(hand_of_cards, ("roxy_st",), (CardRanks.SILVER, CardRanks.GOLD))
            if IBattleStrategy.fight_turn == 2 and roxy_st_ids.size > 0:
                DogsFloor4BattleStrategy.taunt_removed = True
                print("Removing taunt with Roxy!")
                return int(roxy_st_ids[-1])

            if not roxy_st_ids.size:
                # We haven't removed the taunt and don't have a good Roxy ST saved to remove it...
                drag = self._best_merge_drag_indices(
                    hand_of_cards,
                    ("roxy_st",),
                    rank=CardRanks.BRONZE,
                    log_label="roxy_st BRONZE merge",
                )
                if drag is not None:
                    return drag

        # First, play Nasiens ultimate if we have it
        nasiens_ult_id = self._matching_card_ids(hand_of_cards, ("nasi_ult",))
        if len(nasiens_ult_id) > 0 and not DogsFloor4BattleStrategy.removed_damage_cap:
            return nasiens_ult_id[-1]

        # Merge ST gauge cards if possible
        if IBattleStrategy.fight_turn <= 2:
            drag = self._best_merge_drag_indices(
                hand_of_cards, GAUGE_REMOVAL_TEMPLATES, log_label="gauge merge (insufficient gold)"
            )
            if drag is not None:
                return drag

            return self._smarter_phase3(hand_of_cards, picked_cards)

        # At this point, let's see if we can remove the damage cap thingy...
        screenshot, window_location = capture_window()
        # Safety net:
        has_damage_cap = not DogsFloor4BattleStrategy.removed_damage_cap
        # DogsFloor4BattleStrategy.removed_damage_cap = not has_damage_cap
        print("Do we still have a damage cap?", has_damage_cap, " Do we see it?", find(vio.dogs_damage_cap, screenshot))
        if has_damage_cap:
            # First, check if we've played enough
            played_st_gauge_ids = self._tr(picked_cards, ST_GAUGE_TEMPLATES, (CardRanks.GOLD,))
            played_lillia_ids = self._tr(picked_cards, ("lillia_aoe",), (CardRanks.GOLD,))
            if played_st_gauge_ids.size >= 2 or played_lillia_ids.size >= 1:
                DogsFloor4BattleStrategy.removed_damage_cap = True
                DogsFloor4BattleStrategy._defer_ham_cards_until_after_fight_turn = IBattleStrategy.fight_turn + 1
                return self._smarter_phase3(hand_of_cards, picked_cards)

            st_gauge_ids = self._tr(hand_of_cards, ST_GAUGE_TEMPLATES, (CardRanks.GOLD,))
            lillia_aoe_ids = self._tr(hand_of_cards, ("lillia_aoe",), (CardRanks.GOLD,))
            print(
                "These many gold ST gauge and lillia_aoe cards available:",
                st_gauge_ids.size,
                lillia_aoe_ids.size,
            )

            # Count GOLD ST gauge in hand plus already played this turn (picked_cards).
            if lillia_aoe_ids.size == 0 and (played_st_gauge_ids.size + st_gauge_ids.size) < 2:
                drag = self._best_merge_drag_indices(
                    hand_of_cards, GAUGE_REMOVAL_TEMPLATES, log_label="gauge merge (insufficient gold)"
                )
                if drag is not None:
                    return drag
                print("Not enough gold cards to remove gauges...")
                print(f"{played_st_gauge_ids.size} GOLD played and {st_gauge_ids.size} GOLD in hand.")
                return self._smarter_phase3(hand_of_cards, picked_cards)

            # Escalin talent (gauge removal): Roxy — play SILVER/GOLD roxy_st if playable; else Nasi ult if SILVER/GOLD roxy_st is DISABLED; else talent.
            if type(self).roxy_in_team and not DogsFloor4BattleStrategy.taunt_removed:
                roxy_st_sg_ranks = (CardRanks.SILVER, CardRanks.GOLD)
                playable_roxy_st = self._matching_card_ids(hand_of_cards, ("roxy_st",), ranks=roxy_st_sg_ranks)
                if playable_roxy_st:
                    print("Phase 3: playing SILVER/GOLD roxy_st instead of Escalin talent")
                    DogsFloor4BattleStrategy.taunt_removed = True
                    return playable_roxy_st[-1]
                roxy_st_idx = self._tr(hand_of_cards, ("roxy_st",), roxy_st_sg_ranks)
                nasiens_ult_here = self._matching_card_ids(hand_of_cards, ("nasi_ult",))
                if nasiens_ult_here and any(hand_of_cards[int(i)].card_type == CardTypes.DISABLED for i in roxy_st_idx):
                    print("Phase 3: Nasi ult to unlock DISABLED SILVER/GOLD roxy_st")
                    return nasiens_ult_here[-1]

            if (
                not DogsFloor4BattleStrategy.taunt_removed
                and find_and_click(vio.talent_escalin, screenshot, window_location, threshold=0.6)
                and card_turn == 0
            ):
                print("Phase 3: activating Escalin talent!")
                DogsFloor4BattleStrategy.taunt_removed = True
                time.sleep(2.5)

            if played_st_gauge_ids.size == 1:
                # Gotta click light dog after we've played the first remove gauge card
                print("Clicking light dog after playing the first remove gauge card!")
                click_im(Coordinates.get_coordinates("light_dog"), window_location)
                time.sleep(1)

            if lillia_aoe_ids.size:
                DogsFloor4BattleStrategy.removed_damage_cap = True
                DogsFloor4BattleStrategy._defer_ham_cards_until_after_fight_turn = IBattleStrategy.fight_turn + 1
                print("Playing a GOLD Lillia card!")
                return int(lillia_aoe_ids[-1])

            if played_st_gauge_ids.size <= 1:
                # Play gold ST gauge cards (two total to clear cap when no Lillia AOE).
                st_gauge_pick_id = int(st_gauge_ids[-1]) if st_gauge_ids.size else -1
                if st_gauge_pick_id != -1:
                    print("Playing a GOLD ST gauge card!")
                    if played_st_gauge_ids.size == 1:
                        DogsFloor4BattleStrategy.removed_damage_cap = True
                        DogsFloor4BattleStrategy._defer_ham_cards_until_after_fight_turn = (
                            IBattleStrategy.fight_turn + 1
                        )
                        print(
                            f"Damage cap removed on fight turn {IBattleStrategy.fight_turn}! "
                            f"HAM allowed starting fight turn "
                            f"{DogsFloor4BattleStrategy._defer_ham_cards_until_after_fight_turn}."
                        )
                    return st_gauge_pick_id

        else:

            # NOTE: Let's *not* play Escalin talent here, it may remove Nasiens buffs!

            # Re-enable Lillia / ST gauge cards, we can/should play them here -- Maybe not needed, but just in case
            for i in range(len(hand_of_cards)):
                if self._card_matches_any(hand_of_cards[i], GAUGE_REMOVAL_TEMPLATES):
                    hand_of_cards[i].card_type = CardTypes.ATTACK
            # Damage cap not visible: go HAM — play Escalin and Roxy's cards like crazy
            if IBattleStrategy.fight_turn < DogsFloor4BattleStrategy._defer_ham_cards_until_after_fight_turn:
                print(
                    f"We can't play HAM cards yet! fight_turn={IBattleStrategy.fight_turn}, "
                    f"HAM allowed when fight_turn >= "
                    f"{DogsFloor4BattleStrategy._defer_ham_cards_until_after_fight_turn}."
                )
                return self._smarter_phase3(hand_of_cards, picked_cards)
            print("No more damage cap, let's go HAM!")
            for templates in (
                ("escalin_ult",),
                ("escalin_aoe",),
                ("escalin_st",),
                ("roxy_st", "roxy_ult"),
                ("roxy_aoe",),
            ):
                ids = self._matching_card_ids(hand_of_cards, templates)
                if ids:
                    return ids[-1]

        return self._smarter_phase3(hand_of_cards, picked_cards)

    def _smarter_phase3(self, hand_of_cards: list[Card], picked_cards: list[Card]) -> int:
        """Adjust the hand, then ask Smarter for the next card index.

        Hides Escalin cards from the default strategy (stance/AOE disabled, ult
        marked as ground). If the damage cap is still active and Roxy is on the
        team, also marks one SILVER or GOLD Roxy ST card as ground so it is not
        chosen until explicit phase-3 logic plays it.
        """
        roxy_st_hi = (CardRanks.SILVER, CardRanks.GOLD)
        # Keep Escalin off Smarter's pick list for this delegation.
        for i in range(len(hand_of_cards)):
            if self._card_matches_any(hand_of_cards[i], ("escalin_st", "escalin_aoe")):
                print("Disabling Escalin cards")
                hand_of_cards[i].card_type = CardTypes.DISABLED
            elif self._card_matches_any(hand_of_cards[i], ("escalin_ult",)):
                print("Disabling Escalin ult")
                hand_of_cards[i].card_type = CardTypes.GROUND
        # Pre-cap: hide one high-rank Roxy ST from Smarter until phase-3 logic plays it.
        if type(self).roxy_in_team and not DogsFloor4BattleStrategy.removed_damage_cap:
            roxy_st_saveable = self._tr(hand_of_cards, ("roxy_st",), roxy_st_hi)
            if roxy_st_saveable.size > 0:
                hand_of_cards[int(roxy_st_saveable[-1])].card_type = CardTypes.GROUND

        # If ALL are ground, just move a card...
        if hand_of_cards and all(c.card_type == CardTypes.GROUND for c in hand_of_cards):
            print("All cards are ground, just moving a card...")
            return [-1, -2]
            # rx = self._tr(hand_of_cards, ("roxy_st",), roxy_st_hi)
            # if rx.size > 0:
            #     hand_of_cards[int(rx[-1])].card_type = CardTypes.DISABLED

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

    def _tr(self, cards: list[Card], templates: Sequence[str], ranks: Sequence[CardRanks]) -> np.ndarray:
        """Indices where template matches and card rank is in ``ranks`` (any ``card_type``)."""
        if not ranks:
            return np.array([], dtype=np.intp)
        r = np.array([c.card_rank.value for c in cards])
        allowed = np.array([x.value for x in ranks])
        template_ok = np.array([self._card_matches_any(c, templates) for c in cards])
        return np.where(template_ok & np.isin(r, allowed))[0]

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

    def _best_merge_drag_indices(
        self,
        hand_of_cards: list[Card],
        templates: Sequence[str],
        *,
        rank: CardRanks | None = None,
        log_label: str | None = None,
    ) -> tuple[int, int] | None:
        """Drag origin→target to merge two cards matching ``templates``.

        Scan copy sets matching cards to ATTACK so merge prediction sees them (hand may use GROUND).

        Prefer the rightmost merge: maximize target index b, then origin a (lexicographic on (b, a)).
        """
        n = len(hand_of_cards)
        if n < 2:
            return None
        scan = deepcopy(hand_of_cards)
        for card in scan:
            if self._card_matches_any(card, templates):
                card.card_type = CardTypes.ATTACK
        best: tuple[int, int] | None = None
        for a in range(n - 1):
            for b in range(a + 1, n):
                ca, cb = scan[a], scan[b]
                if not self._card_matches_any(ca, templates):
                    continue
                if not self._card_matches_any(cb, templates):
                    continue
                if rank is not None and (ca.card_rank != rank or cb.card_rank != rank):
                    continue
                if not determine_card_merge(ca, cb):
                    continue
                if best is None or (b, a) > (best[1], best[0]):
                    best = (a, b)
        if best is not None:
            label = log_label or "merge"
            print(f"Dragging {label} {best[0]} → {best[1]}")
        return best

    def _card_matches_any(self, card: Card, template_names: Sequence[str]) -> bool:
        if card.card_image is None:
            return False
        return any(find(getattr(vio, template_name), card.card_image) for template_name in template_names)
