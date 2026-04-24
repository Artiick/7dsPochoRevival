import time
from collections.abc import Sequence
from copy import copy, deepcopy
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
MELI3K_TEMPLATES: Final[tuple[str, ...]] = ("meli3k_st", "meli3k_aoe", "meli3k_ult")
GOW_TEMPLATES: Final[tuple[str, ...]] = ("gow_atk", "gow_debuff", "gow_ult")
ROXY_TEMPLATES: Final[tuple[str, ...]] = ("roxy_st", "roxy_aoe", "roxy_ult")
NASI_TEMPLATES: Final[tuple[str, ...]] = ("nasi_heal", "nasi_stun", "nasi_ult")
THONAR_TEMPLATES: Final[tuple[str, ...]] = ("thonar_stance", "thonar_gauge", "thonar_ult")
LILLIA_TEMPLATES: Final[tuple[str, ...]] = ("lillia_st", "lillia_aoe", "lillia_ult")
CUSACK_TEMPLATES: Final[tuple[str, ...]] = ("cusack_cleave", "cusack_gauge")
MERGE_GUARD_TEMPLATES: Final[tuple[str, ...]] = (
    *ESCALIN_TEMPLATES,
    *MELI3K_TEMPLATES,
    *GOW_TEMPLATES,
    *ROXY_TEMPLATES,
    *NASI_TEMPLATES,
    *THONAR_TEMPLATES,
    *LILLIA_TEMPLATES,
    *CUSACK_TEMPLATES,
)
SINS_TEMPLATES: Final[tuple[str, ...]] = (*ESCALIN_TEMPLATES, *MELI3K_TEMPLATES, *GOW_TEMPLATES)
SINS_NON_ULT_TEMPLATES: Final[tuple[str, ...]] = (
    "escalin_st",
    "escalin_aoe",
    "meli3k_st",
    "meli3k_aoe",
    "gow_atk",
    "gow_debuff",
)
PHASE2_ODD_STANCE_SINS_TEMPLATES: Final[tuple[str, ...]] = (
    *ESCALIN_TEMPLATES,
    *MELI3K_TEMPLATES,
    "gow_atk",
)
STANCE_CONTROL_TEMPLATES: Final[tuple[str, ...]] = ("nasi_stun", "thonar_stance")
# Single-target gauge templates (thonar_gauge, cusack_gauge): same cap-removal / merge / GROUND rules as each other; Lillia AOE separate.
ST_GAUGE_TEMPLATES: Final[tuple[str, ...]] = ("thonar_gauge", "cusack_gauge")
GAUGE_REMOVAL_TEMPLATES: Final[tuple[str, ...]] = (*ST_GAUGE_TEMPLATES, "lillia_aoe")


class DogsFloor4BattleStrategy(IBattleStrategy):
    """Dogs Floor 4: per-phase hooks; default card picks from SmarterBattleStrategy."""

    turn = 0
    _phase_initialized = set()
    _last_phase_seen = None
    whale_mode = False
    lillia_in_team = False
    roxy_in_team = False
    meli3k_in_team = False
    bluegow_in_team = False
    taunt_removed = True

    removed_damage_cap = False
    # Minimum fight_turn index where Escalin/Roxy HAM is allowed; block while fight_turn < this (-1 = unset).
    _defer_ham_cards_until_after_fight_turn = -1
    _requested_reset_reason = None

    def _initialize_static_variables(self):
        DogsFloor4BattleStrategy._phase_initialized = set()
        DogsFloor4BattleStrategy._last_phase_seen = None
        DogsFloor4BattleStrategy.removed_damage_cap = False
        DogsFloor4BattleStrategy._defer_ham_cards_until_after_fight_turn = -1
        DogsFloor4BattleStrategy.taunt_removed = True
        DogsFloor4BattleStrategy._requested_reset_reason = None

    def reset_run_state(
        self,
        *,
        whale=False,
        lillia_in_team=False,
        roxy_in_team=False,
        meli3k_in_team=False,
        bluegow_in_team=False,
    ):
        """Called from DogsFloor4Fighter.run before the fight loop."""
        print(
            "Resetting run state with whale mode:",
            whale,
            "Lillia in team:",
            lillia_in_team,
            "Roxy in team:",
            roxy_in_team,
            "Meli3k in team:",
            meli3k_in_team,
            "Blue Gowther in team:",
            bluegow_in_team,
        )
        DogsFloor4BattleStrategy.whale_mode = whale
        DogsFloor4BattleStrategy.lillia_in_team = lillia_in_team
        DogsFloor4BattleStrategy.roxy_in_team = roxy_in_team
        DogsFloor4BattleStrategy.meli3k_in_team = meli3k_in_team
        DogsFloor4BattleStrategy.bluegow_in_team = bluegow_in_team
        self._initialize_static_variables()

    def request_fight_reset(self, reason: str) -> None:
        DogsFloor4BattleStrategy._requested_reset_reason = reason

    def consume_requested_reset_reason(self) -> str | None:
        reason = DogsFloor4BattleStrategy._requested_reset_reason
        DogsFloor4BattleStrategy._requested_reset_reason = None
        return reason

    def _maybe_reset(self, phase_id: str):
        if phase_id not in DogsFloor4BattleStrategy._phase_initialized:
            DogsFloor4BattleStrategy._phase_initialized.add(phase_id)

    def _get_next_card_index_whale(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        phase: int,
        *,
        card_turn: int,
    ) -> int | list[int]:
        if phase == 1:
            return self._get_next_card_index_whale_phase1(hand_of_cards, picked_cards, card_turn)
        if phase == 2:
            return self._get_next_card_index_whale_phase2(hand_of_cards, picked_cards, card_turn)
        return self._get_next_card_index_whale_phase3(hand_of_cards, picked_cards, card_turn)

    def _get_next_card_index_whale_phase1(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        card_turn: int,
    ) -> int | list[int]:
        self._maybe_reset("phase_1_whale")

        if IBattleStrategy.fight_turn > 2:
            self.request_fight_reset("Dogs Floor 4 whale mode: phase 1 went off script, resetting the fight.")
            return 0

        if IBattleStrategy.fight_turn == 1:
            if card_turn in {0, 1}:
                move_action = self._best_nasi_setup_move(hand_of_cards)
                if move_action is None:
                    self.request_fight_reset(
                        "Dogs Floor 4 whale mode: phase 1 turn 1 needed a Nasi setup move, but none was found."
                    )
                    return 0
                return move_action
            if card_turn == 2:
                gow_aoe_id = self._best_card_from_priority(hand_of_cards, [("gow_atk",)])
                if gow_aoe_id == -1:
                    self.request_fight_reset(
                        "Dogs Floor 4 whale mode: phase 1 turn 1 expected Gow AOE, but it was missing."
                    )
                    return 0
                return gow_aoe_id
            meli_aoe_id = self._best_matching_card(hand_of_cards, ("meli3k_aoe",))
            if meli_aoe_id == -1:
                self.request_fight_reset(
                    "Dogs Floor 4 whale mode: phase 1 turn 1 expected Meli3k AOE, but it was missing."
                )
                return 0
            return meli_aoe_id

        if card_turn == 0 and not self._activate_escalin_talent_or_reset("phase 1 turn 2"):
            return 0

        phase1_turn2_priorities: tuple[tuple[str, ...], ...] = (
            ("nasi_heal",),
            ("meli3k_st",),
            ("escalin_aoe",),
            ("escalin_st",),
        )
        idx = self._best_card_from_priority(hand_of_cards, [phase1_turn2_priorities[card_turn]])
        if idx == -1:
            self.request_fight_reset(
                f"Dogs Floor 4 whale mode: phase 1 turn 2 was missing its scripted action {card_turn + 1}."
            )
            return 0
        return idx

    def _get_next_card_index_whale_phase2(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        card_turn: int,
    ) -> int | list[int]:
        self._maybe_reset("phase_2_whale")

        if IBattleStrategy.fight_turn == 1:
            return self._phase2_turn1_whale_action(hand_of_cards, picked_cards, card_turn)

        if IBattleStrategy.fight_turn % 2 == 0:
            return self._phase2_even_turn_whale_action(hand_of_cards, picked_cards, card_turn)

        return self._phase2_odd_turn_whale_action(hand_of_cards, picked_cards, card_turn)

    def _phase2_turn1_whale_action(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        card_turn: int,
    ) -> int | list[int]:
        nasi_ids = self._matching_card_ids(hand_of_cards, NASI_TEMPLATES)
        hi_stun_ids = self._matching_card_ids(hand_of_cards, ("nasi_stun",), ranks=(CardRanks.SILVER, CardRanks.GOLD))
        if card_turn == 0:
            if len(nasi_ids) >= 2:
                random_nasi_id = self._phase2_random_nasi_opener_id(hand_of_cards)
                if random_nasi_id == -1:
                    self.request_fight_reset(
                        "Dogs Floor 4 whale mode: phase 2 turn 1 expected an opener Nasi card, but none was usable."
                    )
                    return 0
                return random_nasi_id
            if len(nasi_ids) == 1 and hi_stun_ids:
                move_action = self._adjacent_occupied_move(hand_of_cards, hi_stun_ids[-1])
                if move_action is None:
                    self.request_fight_reset(
                        "Dogs Floor 4 whale mode: phase 2 turn 1 needed to move the lone silver/gold Nasi stun, but no move target was found."
                    )
                    return 0
                return move_action
            print(
                "Dogs Floor 4 whale mode: phase 2 turn 1 could not identify the scripted Nasi opener, "
                "so falling back to the odd-turn stance-break logic."
            )
            return self._phase2_odd_turn_whale_action(hand_of_cards, picked_cards, card_turn)

        if card_turn == 1:
            if hi_stun_ids:
                return hi_stun_ids[-1]
            print(
                "Dogs Floor 4 whale mode: phase 2 turn 1 lost sight of the silver/gold Nasi stun, "
                "so falling back to the odd-turn stance-break logic."
            )
            return self._phase2_odd_turn_whale_action(hand_of_cards, picked_cards, card_turn)

        return self._phase2_turn1_whale_nuke_action(hand_of_cards, picked_cards, card_turn)

    def _phase2_turn1_whale_nuke_action(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        card_turn: int,
    ) -> int | list[int]:
        meli_ids = self._matching_card_ids(hand_of_cards, MELI3K_TEMPLATES)
        esca_ids = self._matching_card_ids(hand_of_cards, ESCALIN_TEMPLATES)
        played_meli = self._turn_has_any(picked_cards, MELI3K_TEMPLATES)
        played_esca = self._turn_has_any(picked_cards, ESCALIN_TEMPLATES)

        if meli_ids and esca_ids:
            if not played_esca:
                idx = self._best_card_from_priority(hand_of_cards, [("escalin_st",), ("escalin_aoe",), ("escalin_ult",)])
                if idx != -1:
                    return idx
            idx = self._best_card_from_priority(hand_of_cards, [("meli3k_st",), ("meli3k_aoe",), ("meli3k_ult",)])
            if idx != -1:
                return idx

        if meli_ids and not esca_ids:
            if not played_meli:
                idx = self._best_card_from_priority(hand_of_cards, [("meli3k_st",), ("meli3k_aoe",), ("meli3k_ult",)])
                if idx != -1:
                    return idx
            idx = self._best_card_from_priority(hand_of_cards, [("meli3k_aoe",), ("meli3k_st",), ("meli3k_ult",)])
            if idx != -1:
                return idx

        if esca_ids and not meli_ids:
            esca_st_ids = self._matching_card_ids(hand_of_cards, ("escalin_st",))
            if len(esca_st_ids) >= 2:
                return esca_st_ids[-1]
            idx = self._best_card_from_priority(hand_of_cards, [("escalin_st",), ("escalin_aoe",)])
            if idx != -1:
                return idx

        filler_action = self._phase2_support_filler_action(hand_of_cards, picked_cards, allow_silver_stun_merge=False)
        if filler_action != -1:
            return filler_action

        fallback_action = self._phase2_last_resort_action(hand_of_cards, picked_cards)
        if fallback_action != -1:
            return fallback_action

        self.request_fight_reset(
            "Dogs Floor 4 whale mode: phase 2 turn 1 reached its filler path with no safe action available."
        )
        return 0

    def _phase2_even_turn_whale_action(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        card_turn: int,
    ) -> int | list[int]:
        nuke_action = self._phase2_even_turn_nuke_action(hand_of_cards)
        if nuke_action != -1:
            return nuke_action

        filler_action = self._phase2_support_filler_action(hand_of_cards, picked_cards, allow_silver_stun_merge=False)
        if filler_action != -1:
            return filler_action

        fallback_action = self._phase2_last_resort_action(hand_of_cards, picked_cards)
        if fallback_action != -1:
            return fallback_action

        self.request_fight_reset(
            "Dogs Floor 4 whale mode: phase 2 even turn had neither a nuke card nor a safe filler action."
        )
        return 0

    def _phase2_odd_turn_whale_action(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        card_turn: int,
    ) -> int | list[int]:
        played_heal = self._turn_has_any(picked_cards, ("nasi_heal",))
        played_hi_stun = self._turn_has_any(picked_cards, ("nasi_stun",), ranks=(CardRanks.SILVER, CardRanks.GOLD))
        played_meli_ult = self._turn_has_any(picked_cards, ("meli3k_ult",))
        sins_played_count = self._turn_match_count(picked_cards, PHASE2_ODD_STANCE_SINS_TEMPLATES)

        if not played_heal:
            nasi_heal_id = self._best_matching_card(hand_of_cards, ("nasi_heal",))
            if nasi_heal_id != -1:
                return nasi_heal_id

        if played_hi_stun or played_meli_ult or sins_played_count >= 3:
            nuke_action = self._phase2_even_turn_nuke_action(hand_of_cards)
            if nuke_action != -1:
                return nuke_action
            filler_action = self._phase2_support_filler_action(hand_of_cards, picked_cards, allow_silver_stun_merge=False)
            if filler_action != -1:
                return filler_action
            fallback_action = self._phase2_last_resort_action(hand_of_cards, picked_cards)
            if fallback_action != -1:
                return fallback_action
            self.request_fight_reset(
                "Dogs Floor 4 whale mode: phase 2 odd turn cleared stance, but no follow-up action was available."
            )
            return 0

        hi_stun_id = self._best_matching_card(hand_of_cards, ("nasi_stun",), ranks=(CardRanks.SILVER, CardRanks.GOLD))
        if hi_stun_id != -1:
            return hi_stun_id

        meli_ult_id = self._best_matching_card(hand_of_cards, ("meli3k_ult",))
        if meli_ult_id != -1:
            return meli_ult_id

        sins_action = self._phase2_odd_turn_sins_sequence_action(hand_of_cards, picked_cards)
        if sins_action != -1:
            return sins_action

        self.request_fight_reset(
            "Dogs Floor 4 whale mode: phase 2 odd turn could not remove stance with either Nasi stun or the 3-Sins sequence."
        )
        return 0

    def _get_next_card_index_whale_phase3(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        card_turn: int,
    ) -> int | list[int]:
        self._maybe_reset("phase_3_whale")

        if IBattleStrategy.fight_turn == 1:
            return self._phase3_turn1_whale_action(hand_of_cards, picked_cards, card_turn)
        if IBattleStrategy.fight_turn == 2:
            return self._phase3_turn2_whale_action(hand_of_cards, picked_cards, card_turn)
        if IBattleStrategy.fight_turn == 3:
            return self._phase3_turn3_whale_action(hand_of_cards, picked_cards, card_turn)
        return self._phase3_nuke_action(hand_of_cards, picked_cards)

    def _phase3_turn1_whale_action(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        card_turn: int,
    ) -> int | list[int]:
        if card_turn == 0:
            nasi_ult_id = self._best_matching_card(hand_of_cards, ("nasi_ult",))
            if nasi_ult_id == -1:
                self.request_fight_reset("Dogs Floor 4 whale mode: phase 3 turn 1 must open with Nasi ult.")
                return 0
            return nasi_ult_id
        return self._phase3_setup_action(
            hand_of_cards,
            picked_cards,
            card_turn=card_turn,
            prefer_heal=True,
            use_reserved_on_last_action=False,
        )

    def _phase3_turn2_whale_action(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        card_turn: int,
    ) -> int | list[int]:
        return self._phase3_setup_action(
            hand_of_cards,
            picked_cards,
            card_turn=card_turn,
            prefer_heal=True,
            use_reserved_on_last_action=card_turn >= 3,
        )

    def _phase3_turn3_whale_action(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        card_turn: int,
    ) -> int | list[int]:
        gow_ult_missing_in_hand = self._best_matching_card(hand_of_cards, ("gow_ult",)) == -1
        gow_ult_already_played = self._turn_has_any(picked_cards, ("gow_ult",))
        if gow_ult_missing_in_hand and not gow_ult_already_played:
            self.request_fight_reset("Dogs Floor 4 whale mode: phase 3 turn 3 expected Gow ult, so resetting.")
            return 0

        idx = self._best_card_from_priority(
            hand_of_cards,
            [
                ("gow_ult",),
                ("escalin_ult",),
                ("meli3k_ult",),
                ("escalin_aoe",),
                ("meli3k_aoe",),
                ("nasi_heal",),
                ("gow_debuff",),
                ("gow_atk",),
                ("nasi_stun",),
            ],
        )
        if idx != -1:
            return idx

        noop_move = self._phase3_turn3_noop_move(hand_of_cards)
        if noop_move is not None:
            print("Dogs Floor 4 whale mode: phase 3 turn 3 had no junk card, so using a 6 -> 7 hand cycle move.")
            return noop_move

        self.request_fight_reset("Dogs Floor 4 whale mode: phase 3 turn 3 had no valid scripted follow-up.")
        return 0

    def _phase3_nuke_action(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
    ) -> int | list[int]:
        idx = self._best_card_from_priority(
            hand_of_cards,
            [
                ("escalin_ult",),
                ("meli3k_ult",),
                ("escalin_aoe",),
                ("meli3k_aoe",),
                ("escalin_st",),
                ("meli3k_st",),
                ("gow_ult",),
                ("gow_debuff",),
                ("gow_atk",),
            ],
        )
        if idx != -1:
            return idx

        filler_action = self._phase2_support_filler_action(hand_of_cards, picked_cards, allow_silver_stun_merge=False)
        if filler_action != -1:
            return filler_action

        self.request_fight_reset("Dogs Floor 4 whale mode: phase 3 nuke phase ran out of usable actions.")
        return 0

    def _phase2_even_turn_nuke_action(self, hand_of_cards: list[Card]) -> int:
        return self._best_card_from_priority(
            hand_of_cards,
            [
                ("escalin_st",),
                ("meli3k_st",),
                ("escalin_aoe",),
                ("meli3k_aoe",),
                ("escalin_ult",),
                ("meli3k_ult",),
            ],
        )

    def _phase2_odd_turn_sins_sequence_action(self, hand_of_cards: list[Card], picked_cards: list[Card]) -> int:
        sins_played_count = self._turn_match_count(picked_cards, PHASE2_ODD_STANCE_SINS_TEMPLATES)
        if sins_played_count >= 2:
            return self._best_card_from_priority(
                hand_of_cards,
                [("meli3k_st",), ("meli3k_aoe",), ("meli3k_ult",)],
            )

        future_meli_ids = self._matching_card_ids(hand_of_cards, MELI3K_TEMPLATES)
        non_meli_sins_id = self._best_card_from_priority(
            hand_of_cards,
            [("gow_atk",), ("escalin_st",), ("escalin_aoe",), ("escalin_ult",)],
        )
        if non_meli_sins_id != -1 and future_meli_ids:
            return non_meli_sins_id

        if len(future_meli_ids) >= 2 - sins_played_count + 1:
            return self._best_card_from_priority(
                hand_of_cards,
                [("meli3k_st",), ("meli3k_aoe",), ("meli3k_ult",)],
            )

        return -1

    def _phase3_setup_action(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        *,
        card_turn: int,
        prefer_heal: bool,
        use_reserved_on_last_action: bool,
    ) -> int | list[int]:
        if prefer_heal and not self._turn_has_any(picked_cards, ("nasi_heal",)):
            nasi_heal_id = self._best_matching_card(hand_of_cards, ("nasi_heal",))
            if nasi_heal_id != -1:
                return nasi_heal_id

        if self._best_matching_card(hand_of_cards, ("gow_ult",)) == -1:
            preserve_action = self._phase3_gow_setup_action(
                hand_of_cards,
                use_reserved_on_last_action=use_reserved_on_last_action,
            )
            if preserve_action != -1:
                return preserve_action
            self.request_fight_reset(
                "Dogs Floor 4 whale mode: phase 3 setup needed to preserve a Gow card, but no safe preserve action was found."
            )
            return 0

        esca_ult_missing = self._best_matching_card(hand_of_cards, ("escalin_ult",)) == -1
        meli_ult_missing = self._best_matching_card(hand_of_cards, ("meli3k_ult",)) == -1
        if esca_ult_missing:
            preserve_action = self._phase3_preserve_unit_action(
                hand_of_cards,
                ESCALIN_TEMPLATES,
                keep_one_aoe=True,
                use_reserved_on_last_action=use_reserved_on_last_action,
            )
            if preserve_action != -1:
                return preserve_action
            self.request_fight_reset(
                "Dogs Floor 4 whale mode: phase 3 setup needed to preserve an Escalin card, but no safe preserve action was found."
            )
            return 0
        if meli_ult_missing:
            preserve_action = self._phase3_preserve_unit_action(
                hand_of_cards,
                MELI3K_TEMPLATES,
                keep_one_aoe=True,
                use_reserved_on_last_action=use_reserved_on_last_action,
            )
            if preserve_action != -1:
                return preserve_action
            self.request_fight_reset(
                "Dogs Floor 4 whale mode: phase 3 setup needed to preserve a Meli3k card, but no safe preserve action was found."
            )
            return 0

        reserved_ids = set()
        extra_aoe_id = self._best_card_from_priority(hand_of_cards, [("escalin_aoe",), ("meli3k_aoe",)])
        if extra_aoe_id != -1:
            reserved_ids.add(extra_aoe_id)
        idx = self._best_card_from_priority(
            hand_of_cards,
            [
                ("gow_debuff",),
                ("gow_atk",),
                ("nasi_heal",),
                ("nasi_stun",),
                ("nasi_ult",),
                ("escalin_st",),
                ("meli3k_st",),
            ],
            exclude_ids=reserved_ids,
        )
        if idx != -1:
            return idx
        if extra_aoe_id != -1:
            move_action = self._adjacent_occupied_move(hand_of_cards, extra_aoe_id)
            if move_action is not None:
                return move_action
        self.request_fight_reset("Dogs Floor 4 whale mode: phase 3 setup ran out of preserve/cycle actions.")
        return 0

    def _phase3_gow_setup_action(
        self,
        hand_of_cards: list[Card],
        *,
        use_reserved_on_last_action: bool,
    ) -> int | list[int]:
        gow_ids = self._matching_card_ids(hand_of_cards, GOW_TEMPLATES)
        if not gow_ids:
            return -1

        reserve_builder_id = gow_ids[-1]
        spendable_gow_ids = [idx for idx in gow_ids if idx != reserve_builder_id]
        if spendable_gow_ids:
            return spendable_gow_ids[-1]

        if use_reserved_on_last_action:
            return reserve_builder_id

        move_action = self._adjacent_occupied_move(hand_of_cards, reserve_builder_id)
        if move_action is not None:
            return move_action

        return reserve_builder_id

    def _phase3_preserve_unit_action(
        self,
        hand_of_cards: list[Card],
        unit_templates: Sequence[str],
        *,
        keep_one_aoe: bool,
        use_reserved_on_last_action: bool,
    ) -> int | list[int]:
        reserved_ids = set()
        reserve_builder_id = self._best_card_from_priority(
            hand_of_cards,
            [(tuple(t for t in unit_templates if "aoe" in t)), unit_templates],
        )
        if reserve_builder_id != -1:
            reserved_ids.add(reserve_builder_id)

        if keep_one_aoe:
            extra_aoe_id = self._best_card_from_priority(hand_of_cards, [("escalin_aoe",), ("meli3k_aoe",)])
            if extra_aoe_id != -1:
                reserved_ids.add(extra_aoe_id)

        spend_id = self._best_card_from_priority(
            hand_of_cards,
            [
                ("gow_debuff",),
                ("gow_atk",),
                ("nasi_heal",),
                ("nasi_stun",),
                unit_templates,
                ("nasi_ult",),
            ],
            exclude_ids=reserved_ids,
        )
        if spend_id != -1:
            return spend_id

        if reserve_builder_id != -1:
            if use_reserved_on_last_action:
                return reserve_builder_id
            move_action = self._adjacent_occupied_move(hand_of_cards, reserve_builder_id)
            if move_action is not None:
                return move_action

        return -1

    def _phase3_turn3_noop_move(self, hand_of_cards: list[Card]) -> list[int] | None:
        if len(hand_of_cards) > 7:
            idx6 = hand_of_cards[6]
            idx7 = hand_of_cards[7]
            if idx6.card_type not in (CardTypes.NONE, CardTypes.GROUND) and idx7.card_type not in (
                CardTypes.NONE,
                CardTypes.GROUND,
            ):
                return [6, 7]
        return None

    def _phase2_support_filler_action(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        *,
        allow_silver_stun_merge: bool,
    ) -> int | list[int]:
        bronze_merge = self._best_merge_drag_indices(hand_of_cards, ("nasi_stun",), rank=CardRanks.BRONZE)
        if bronze_merge is not None:
            return bronze_merge

        if allow_silver_stun_merge:
            silver_merge = self._best_merge_drag_indices(hand_of_cards, ("nasi_stun",), rank=CardRanks.SILVER)
            if silver_merge is not None:
                return silver_merge

        if not self._turn_has_any(picked_cards, ("nasi_heal",)):
            nasi_heal_id = self._best_matching_card(hand_of_cards, ("nasi_heal",))
            if nasi_heal_id != -1:
                return nasi_heal_id

        gow_ids = self._matching_card_ids(hand_of_cards, GOW_TEMPLATES)
        gow_id = self._best_card_from_priority(hand_of_cards, [("gow_debuff",), ("gow_atk",)])
        if gow_id != -1 and len(gow_ids) >= 2:
            return gow_id

        return -1

    def _phase2_last_resort_action(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
    ) -> int:
        return self._best_card_from_priority(
            hand_of_cards,
            [
                ("nasi_heal",),
                ("gow_debuff",),
                ("gow_atk",),
                ("nasi_stun",),
                ("escalin_st",),
                ("meli3k_st",),
                ("escalin_aoe",),
                ("meli3k_aoe",),
            ],
        )

    def _best_nasi_setup_move(self, hand_of_cards: list[Card]) -> list[int] | None:
        nasi_ids = self._matching_card_ids(hand_of_cards, ("nasi_heal", "nasi_stun"))
        if not nasi_ids:
            nasi_ids = self._matching_card_ids(hand_of_cards, ("nasi_ult",))
        if not nasi_ids:
            return None
        origin_idx = nasi_ids[-1]
        return self._adjacent_occupied_move(hand_of_cards, origin_idx)

    def _phase2_random_nasi_opener_id(self, hand_of_cards: list[Card]) -> int:
        candidate_ids = [
            idx
            for idx in self._matching_card_ids(hand_of_cards, NASI_TEMPLATES)
            if hand_of_cards[idx].card_rank not in {CardRanks.SILVER, CardRanks.GOLD}
            or not self._card_matches_any(hand_of_cards[idx], ("nasi_stun",))
        ]
        if candidate_ids:
            return min(candidate_ids, key=lambda idx: (hand_of_cards[idx].card_rank.value, -idx))

        fallback_ids = self._matching_card_ids(hand_of_cards, NASI_TEMPLATES)
        if fallback_ids:
            return min(fallback_ids, key=lambda idx: (hand_of_cards[idx].card_rank.value, -idx))
        return -1

    def _activate_escalin_talent_or_reset(self, context_label: str) -> bool:
        screenshot, window_location = capture_window()
        marker_was_visible = self._dogs_talent_marker_visible(screenshot)
        for attempt in range(1, 4):
            print(f"Dogs Floor 4 whale mode: clicking Escalin talent for {context_label} (attempt {attempt}/3).")
            click_im(Coordinates.get_coordinates("talent"), window_location)

            deadline = time.perf_counter() + 1.2
            while time.perf_counter() < deadline:
                time.sleep(0.08)
                screenshot, _ = capture_window()
                if not self._dogs_talent_marker_visible(screenshot):
                    print(f"Dogs Floor 4 whale mode: confirmed Escalin talent for {context_label}.")
                    time.sleep(2.5)
                    return True

            if not marker_was_visible:
                print(
                    "Dogs Floor 4 whale mode: the Dogs talent marker was not visible before the click, "
                    "so proceeding after the normal talent delay."
                )
                time.sleep(2.5)
                return True

        self.request_fight_reset(
            f"Dogs Floor 4 whale mode: expected Escalin talent before {context_label}, but the button was not found."
        )
        return False

    @staticmethod
    def _dogs_talent_marker_visible(screenshot) -> bool:
        return find(vio.dogs_escalin_talent, screenshot, threshold=0.75)

    def _adjacent_occupied_move(self, hand_of_cards: list[Card], origin_idx: int) -> list[int] | None:
        if not (0 <= origin_idx < len(hand_of_cards)):
            return None
        for step in range(1, len(hand_of_cards)):
            for target_idx in (origin_idx + step, origin_idx - step):
                if not (0 <= target_idx < len(hand_of_cards)):
                    continue
                if hand_of_cards[target_idx].card_type in (CardTypes.NONE, CardTypes.GROUND):
                    continue
                return [origin_idx, target_idx]
        return None

    def _best_card_from_priority(
        self,
        hand_of_cards: list[Card],
        priorities: Sequence[Sequence[str]],
        *,
        exclude_ids: set[int] | None = None,
    ) -> int:
        blocked = exclude_ids or set()
        for template_names in priorities:
            matching_ids = [idx for idx in self._matching_card_ids(hand_of_cards, template_names) if idx not in blocked]
            if matching_ids:
                return matching_ids[-1]
        return -1

    def _turn_has_any(
        self,
        picked_cards: list[Card],
        template_names: Sequence[str],
        *,
        ranks: Sequence[CardRanks] | None = None,
    ) -> bool:
        return self._turn_match_count(picked_cards, template_names, ranks=ranks) > 0

    def _turn_match_count(
        self,
        picked_cards: list[Card],
        template_names: Sequence[str],
        *,
        ranks: Sequence[CardRanks] | None = None,
    ) -> int:
        allowed_ranks = frozenset(ranks) if ranks is not None else None
        count = 0
        for card in picked_cards:
            if card.card_image is None:
                continue
            if allowed_ranks is not None and card.card_rank not in allowed_ranks:
                continue
            if self._card_matches_any(card, template_names):
                count += 1
        return count

    def get_next_card_index(
        self, hand_of_cards: list[Card], picked_cards: list[Card], phase: int, card_turn=0, **kwargs
    ) -> int:
        if phase == 1 and DogsFloor4BattleStrategy._last_phase_seen != 1:
            self._initialize_static_variables()

        DogsFloor4BattleStrategy._last_phase_seen = phase

        if type(self).whale_mode:
            return self._get_next_card_index_whale(hand_of_cards, picked_cards, phase, card_turn=card_turn)

        ## Common logic -- Protect gauge removal cards at all costs (non-Lillia teams only)!

        if not type(self).lillia_in_team:
            # Mark ST gauge cards GROUND so Smarter skips them unless phase logic explicitly plays them.
            ids = [i for i, c in enumerate(hand_of_cards) if self._card_matches_any(c, ST_GAUGE_TEMPLATES)]
            if ids:
                n_gold = sum(bool(hand_of_cards[i].card_rank == CardRanks.GOLD) for i in ids)
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
            # Lillia teams: save the best AOE in phases 1/2, but hide all AOEs in phase 3 until cap-removal logic uses one.
            lillia_aoe_ids = self._matching_card_ids(
                hand_of_cards,
                ("lillia_aoe",),
                include_unplayable=True,
            )
            if phase == 3:
                for i in lillia_aoe_ids:
                    hand_of_cards[i].card_type = CardTypes.GROUND
            elif lillia_aoe_ids:
                hand_of_cards[lillia_aoe_ids[-1]].card_type = CardTypes.GROUND

        # Phase-specify logic here

        if phase == 1:
            return self.get_next_card_index_phase1(hand_of_cards, picked_cards, card_turn=card_turn)
        if phase == 2:
            return self.get_next_card_index_phase2(hand_of_cards, picked_cards, card_turn=card_turn)
        return self.get_next_card_index_phase3(hand_of_cards, picked_cards, card_turn=card_turn)

    def get_next_card_index_phase1(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_1")

        # Let's start with Escalin's talent only on turn 2-onwards
        if IBattleStrategy.fight_turn > 1:
            screenshot, window_location = capture_window()
            if find_and_click(vio.talent_escalin, screenshot, window_location, threshold=0.7):
                print("Phase 1: activating Escalin talent!")
                time.sleep(2.5)

        # First, play one stance-control card on odd turns; otherwise hide them from Smarter.
        attack_debuff_ids = self._matching_card_ids(hand_of_cards, STANCE_CONTROL_TEMPLATES)
        played_attack_debuff_ids = self._matching_card_ids(picked_cards, STANCE_CONTROL_TEMPLATES)
        if attack_debuff_ids:
            last_ad = attack_debuff_ids[-1]
            even_fight_turn = IBattleStrategy.fight_turn % 2 == 0
            # Even turns: disable stance cancel. Odd + already played one: ground another. Odd + none played: play one.
            if even_fight_turn or played_attack_debuff_ids:
                hand_of_cards[last_ad].card_type = CardTypes.GROUND
                print("Disabling stance cancel cards.")
            else:
                print("Playing a stance-control card to remove stance!")
                return last_ad

        # Phase 1: First turn, play a sequence of cards
        if IBattleStrategy.fight_turn == 1:

            if DogsFloor4BattleStrategy.roxy_in_team:
                cusack_cleave_id = self._best_matching_card(hand_of_cards, ("cusack_cleave",))
                if cusack_cleave_id != -1:
                    print("Playing cusack cleave")
                    return cusack_cleave_id

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

            elif DogsFloor4BattleStrategy.lillia_in_team:
                if heal_ids := self._matching_card_ids(hand_of_cards, ("nasi_heal",)):
                    print("Playing nasi heal")
                    return heal_ids[-1]

                if thonar_gauge_ids := self._matching_card_ids(hand_of_cards, ("thonar_gauge",)):
                    print("Playing thonar gauge")
                    return thonar_gauge_ids[-1]

                if lillia_st_ids := self._matching_card_ids(hand_of_cards, ("lillia_st",)):
                    print("Playing lillia st")
                    return lillia_st_ids[-1]

                print("Desired card not found...")

        # Disable stance cancel cards even if level 1
        stance_cancel_ids = self._matching_card_ids(hand_of_cards, ("nasi_stun", "thonar_stance"))
        for i in stance_cancel_ids:
            hand_of_cards[i].card_type = CardTypes.DISABLED
            print("Disabling future stance cancel cards.")

        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def get_next_card_index_phase2(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_2")

        print(f"Phase 2: fight turn {IBattleStrategy.fight_turn}")

        nasiens_ids = self._matching_card_ids(hand_of_cards, NASI_TEMPLATES)
        if card_turn == 0:
            has_nasiens_ult = any(self._card_matches_any(hand_of_cards[i], ("nasi_ult",)) for i in nasiens_ids)

            # If we still have no nasi_ult in hand, try to reshuffle: move the first non-GROUND Nasiens card one slot right.
            if not has_nasiens_ult and nasiens_ids:
                print("Moving Nasiens card to get ult...")
                return [nasiens_ids[-1], nasiens_ids[-1] + 1]

            if not type(self).lillia_in_team:
                # On the first pick only, spend one pick merging any available gauge-removal pair.
                drag = self._best_merge_drag_indices(hand_of_cards, ST_GAUGE_TEMPLATES, log_label="phase 2 gauge merge")
                if drag is not None:
                    return drag

        # Play one stance-control card on odd turns; otherwise hide them from Smarter.
        if attack_debuff_ids := self._matching_card_ids(hand_of_cards, STANCE_CONTROL_TEMPLATES):
            played_attack_debuff_ids = self._matching_card_ids(picked_cards, STANCE_CONTROL_TEMPLATES)
            last_ad = attack_debuff_ids[-1]
            # Even turns: disable stance cancel. Odd + already played one: ground another. Odd + none played: play one.
            if IBattleStrategy.fight_turn % 2 == 0 or played_attack_debuff_ids:
                hand_of_cards[last_ad].card_type = CardTypes.GROUND
                print("Disabling stance cancel cards.")
            else:
                print("Playing a stance-control card to remove stance!")
                return last_ad

        # Do not play Nasiens ult: mark it GROUND so SmarterBattleStrategy skips it (same idea as Escalin above).
        for i in nasiens_ids:
            if self._card_matches_any(hand_of_cards[i], ("nasi_ult",)):
                print("Disabling Nasiens ult!")
                hand_of_cards[i].card_type = CardTypes.GROUND

        # Phase 2: Tuck one SILVER/GOLD roxy_st so Smarter skips it (same pattern as _smarter_phase3).
        roxy_st_hi = (CardRanks.SILVER, CardRanks.GOLD)
        if type(self).roxy_in_team:
            if roxy_st_saveable := self._matching_card_ids(
                hand_of_cards,
                ("roxy_st",),
                ranks=roxy_st_hi,
                include_unplayable=True,
            ):
                hand_of_cards[roxy_st_saveable[-1]].card_type = CardTypes.GROUND
        # All-GROUND confuses downstream; unstick one SILVER/GOLD roxy_st to DISABLED if needed.
        if hand_of_cards and all(c.card_type == CardTypes.GROUND for c in hand_of_cards):
            if rx := self._matching_card_ids(
                hand_of_cards,
                ("roxy_st",),
                ranks=roxy_st_hi,
                include_unplayable=True,
            ):
                hand_of_cards[rx[0]].card_type = CardTypes.DISABLED

        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def get_next_card_index_phase3(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        """Important: In phase 3, fight turns start at 1!"""
        self._maybe_reset("phase_3")

        print(f"Phase 3: fight turn {IBattleStrategy.fight_turn}")
        if IBattleStrategy.fight_turn % 2 == 0 and card_turn == 0:
            print("Dog is putting up a taunt...")
            DogsFloor4BattleStrategy.taunt_removed = False

        # Reserve ST gauge cards unless phase-3 logic explicitly plays them.
        st_gauge_ids = [i for i, card in enumerate(hand_of_cards) if self._card_matches_any(card, ST_GAUGE_TEMPLATES)]
        for i in st_gauge_ids:
            hand_of_cards[i].card_type = CardTypes.GROUND

        # Pre-cap Roxy: BRONZE roxy_st merge when hand has no SILVER/GOLD roxy_st.
        # SILVER/GOLD tuck for Smarter is in _smarter_phase3.
        if (
            not DogsFloor4BattleStrategy.removed_damage_cap
            and not DogsFloor4BattleStrategy.taunt_removed
            and type(self).roxy_in_team
        ):
            if roxy_st_ids := self._matching_card_ids(
                hand_of_cards,
                ("roxy_st",),
                ranks=(CardRanks.SILVER, CardRanks.GOLD),
            ):
                DogsFloor4BattleStrategy.taunt_removed = True
                print("Removing taunt with Roxy!")
                return roxy_st_ids[-1]

            # We haven't removed the taunt and don't have a good Roxy ST saved to remove it...
            drag = self._best_merge_drag_indices(
                hand_of_cards,
                ("roxy_st",),
                rank=CardRanks.BRONZE,
                log_label="roxy_st BRONZE merge",
            )
            if drag is not None:
                return drag

        # Pre-cap: play Nasiens ult before the gauge-removal turns.
        nasiens_ult_id = self._matching_card_ids(hand_of_cards, ("nasi_ult",))
        if nasiens_ult_id and IBattleStrategy.fight_turn <= 2:
            return nasiens_ult_id[-1]

        # Early turns: prioritize gauge merges, otherwise delegate to Smarter immediately.
        if IBattleStrategy.fight_turn <= 2:
            drag = self._best_merge_drag_indices(
                hand_of_cards, ST_GAUGE_TEMPLATES, log_label="gauge merge (insufficient gold)"
            )
            if drag is not None:
                self._maybe_activate_escalin_before_gauge_merge(hand_of_cards, drag, card_turn=card_turn)
                return drag

            return self._smarter_phase3(hand_of_cards, picked_cards)

        # Mid/late phase 3: either remove the damage cap or go HAM after it is gone.
        has_damage_cap = not DogsFloor4BattleStrategy.removed_damage_cap
        if has_damage_cap:
            screenshot, window_location = capture_window()
            # First, check if we've played enough
            played_st_gauge_ids = self._matching_card_ids(
                picked_cards,
                ST_GAUGE_TEMPLATES,
                ranks=(CardRanks.GOLD,),
                include_unplayable=True,
            )
            played_lillia_ids = self._matching_card_ids(
                picked_cards,
                ("lillia_aoe",),
                ranks=(CardRanks.GOLD,),
                include_unplayable=True,
            )
            if len(played_st_gauge_ids) >= 2 or played_lillia_ids:
                DogsFloor4BattleStrategy.removed_damage_cap = True
                DogsFloor4BattleStrategy._defer_ham_cards_until_after_fight_turn = IBattleStrategy.fight_turn + 1
                return self._smarter_phase3(hand_of_cards, picked_cards)

            st_gauge_ids = self._matching_card_ids(
                hand_of_cards,
                ST_GAUGE_TEMPLATES,
                ranks=(CardRanks.GOLD,),
                include_unplayable=True,
            )
            lillia_aoe_ids = self._matching_card_ids(
                hand_of_cards,
                ("lillia_aoe",),
                ranks=(CardRanks.GOLD,),
                include_unplayable=True,
            )
            print(
                "These many gold ST gauge and lillia_aoe cards available:",
                len(st_gauge_ids),
                len(lillia_aoe_ids),
            )

            # Count GOLD ST gauge in hand plus already played this turn (picked_cards).
            if not lillia_aoe_ids and (len(played_st_gauge_ids) + len(st_gauge_ids)) < 2:
                drag = self._best_merge_drag_indices(
                    hand_of_cards, ST_GAUGE_TEMPLATES, log_label="gauge merge (insufficient gold)"
                )
                if drag is not None:
                    self._maybe_activate_escalin_before_gauge_merge(
                        hand_of_cards,
                        drag,
                        card_turn=card_turn,
                        played_gold_st_gauge_count=len(played_st_gauge_ids),
                        screenshot=screenshot,
                        window_location=window_location,
                    )
                    return drag
                print("Not enough gold cards to remove gauges...")
                print(f"{len(played_st_gauge_ids)} GOLD played and {len(st_gauge_ids)} GOLD in hand.")
                return self._smarter_phase3(hand_of_cards, picked_cards)

            if (
                not type(self).lillia_in_team  # We need Escalin talent to remove taunt with Roxy
                and not DogsFloor4BattleStrategy.taunt_removed
                and find_and_click(vio.talent_escalin, screenshot, window_location, threshold=0.7)
                and card_turn == 0
            ):
                print("Phase 3: activating Escalin talent!")
                DogsFloor4BattleStrategy.taunt_removed = True
                time.sleep(2.5)

            if len(played_st_gauge_ids) == 1:
                # Gotta click light dog after we've played the first remove gauge card
                print("Clicking light dog after playing the first remove gauge card!")
                click_im(Coordinates.get_coordinates("light_dog"), window_location)
                time.sleep(1)

            if lillia_aoe_ids:
                DogsFloor4BattleStrategy.removed_damage_cap = True
                DogsFloor4BattleStrategy._defer_ham_cards_until_after_fight_turn = IBattleStrategy.fight_turn + 1
                print("Playing a GOLD Lillia card!")
                return lillia_aoe_ids[-1]

            if len(played_st_gauge_ids) <= 1:
                if not DogsFloor4BattleStrategy.taunt_removed:
                    print("We have enough gold cards but taunt isn't removed :(")
                    return self._smarter_phase3(hand_of_cards, picked_cards)

                # Play gold ST gauge cards (two total to clear cap when no Lillia AOE).
                st_gauge_pick_id = st_gauge_ids[-1] if st_gauge_ids else -1
                if st_gauge_pick_id != -1:
                    print("Playing a GOLD ST gauge card!")
                    if len(played_st_gauge_ids) == 1:
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
            # Do not use Escalin talent here; it may remove Nasiens buffs.
            for i, card in enumerate(hand_of_cards):
                if self._card_matches_any(card, GAUGE_REMOVAL_TEMPLATES):
                    hand_of_cards[i].card_type = CardTypes.ATTACK

            # Damage cap not visible: go HAM — play Escalin and Roxy's cards like crazy
            if IBattleStrategy.fight_turn < DogsFloor4BattleStrategy._defer_ham_cards_until_after_fight_turn:

                if nasiens_ult_id := self._matching_card_ids(hand_of_cards, ("nasi_ult",)):
                    return nasiens_ult_id[-1]

                if escalin_ult_ids := self._matching_card_ids(hand_of_cards, ("escalin_ult",)):
                    return escalin_ult_ids[-1]

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
                ("roxy_aoe",),
                ("roxy_st",),
                (
                    "lillia_ult",
                    "roxy_ult",
                    "thonar_ult",
                ),
                ("lillia_aoe",),
            ):
                if ids := self._matching_card_ids(hand_of_cards, templates):
                    return ids[-1]

            if ult_ids := [
                i
                for i, card in enumerate(hand_of_cards)
                if card.card_type == CardTypes.ULTIMATE and not find(vio.nasi_ult, card.card_image)
            ]:
                return ult_ids[-1]

            if att_deb_ids := sorted(
                [
                    i
                    for i, card in enumerate(hand_of_cards)
                    if card.card_type in {CardTypes.ATTACK, CardTypes.ATTACK_DEBUFF}
                ],
                key=lambda idx: (
                    hand_of_cards[idx].card_rank.value,
                    hand_of_cards[idx].card_type != CardTypes.ATTACK,
                    idx,
                ),
            ):
                return att_deb_ids[-1]

        return self._smarter_phase3(hand_of_cards, picked_cards)

    def _smarter_phase3(self, hand_of_cards: list[Card], picked_cards: list[Card]) -> int:
        """Adjust the hand, then ask Smarter for the next card index.

        Hides Escalin cards from the default strategy (stance/AOE disabled, ult
        marked as ground). If the damage cap is still active and Roxy is on the
        team, also marks one SILVER or GOLD Roxy ST card as ground so it is not
        chosen until explicit phase-3 logic plays it.
        """
        roxy_st_hi = (CardRanks.SILVER, CardRanks.GOLD)
        escalin_hide_type = CardTypes.GROUND if type(self).lillia_in_team else CardTypes.DISABLED
        # Keep Escalin off Smarter's pick list for this delegation.
        for item in hand_of_cards:
            if self._card_matches_any(item, ("escalin_st", "escalin_aoe")):
                print("Disabling Escalin cards")
                item.card_type = escalin_hide_type
            elif self._card_matches_any(item, ("escalin_ult",)):
                print("Disabling Escalin ult")
                item.card_type = CardTypes.GROUND
        # Pre-cap: hide one high-rank Roxy ST from Smarter until phase-3 logic plays it.
        if type(self).roxy_in_team and not DogsFloor4BattleStrategy.removed_damage_cap:
            if roxy_st_saveable := self._matching_card_ids(
                hand_of_cards,
                ("roxy_st",),
                ranks=roxy_st_hi,
                include_unplayable=True,
            ):
                hand_of_cards[roxy_st_saveable[-1]].card_type = CardTypes.GROUND

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

    def _maybe_activate_escalin_before_gauge_merge(
        self,
        hand_of_cards: list[Card],
        drag: tuple[int, int] | None,
        *,
        card_turn: int,
        played_gold_st_gauge_count: int = 0,
        screenshot=None,
        window_location=None,
    ) -> None:
        if type(self).lillia_in_team:
            # If we're using Lillia, let's not remove taunt with Escalin ever!
            return

        if drag is None or card_turn != 0 or DogsFloor4BattleStrategy.taunt_removed:
            return

        future_hand = deepcopy(hand_of_cards)
        for card in future_hand:
            if self._card_matches_any(card, GAUGE_REMOVAL_TEMPLATES):
                card.card_type = CardTypes.ATTACK

        future_hand = self._update_hand_of_cards(future_hand, [drag])
        future_gold_st_gauge_ids = self._matching_card_ids(
            future_hand,
            ST_GAUGE_TEMPLATES,
            ranks=(CardRanks.GOLD,),
            include_unplayable=True,
        )
        if played_gold_st_gauge_count + len(future_gold_st_gauge_ids) < 2:
            return

        if screenshot is None or window_location is None:
            screenshot, window_location = capture_window()
        if find_and_click(vio.talent_escalin, screenshot, window_location, threshold=0.7):
            print("Phase 3: activating Escalin talent before gauge merge!")
            DogsFloor4BattleStrategy.taunt_removed = True
            time.sleep(2.5)

    def _matching_card_ids(
        self,
        hand_of_cards: list[Card],
        template_names: Sequence[str],
        *,
        ranks: Sequence[CardRanks] | None = None,
        include_unplayable: bool = False,
    ) -> list[int]:
        """Return matching card indices sorted by ``(rank, index)`` ascending.

        By default this only returns cards that are currently playable by the
        generic strategy. Set ``include_unplayable=True`` when phase logic needs
        to inspect matching cards regardless of their current ``card_type``.
        """
        allowed_ranks = frozenset(ranks) if ranks is not None else None
        blocked_types = () if include_unplayable else (CardTypes.DISABLED, CardTypes.NONE, CardTypes.GROUND)
        matching_ids = [
            idx
            for idx, card in enumerate(hand_of_cards)
            if card.card_type not in blocked_types
            and self._card_matches_any(card, template_names)
            and (allowed_ranks is None or card.card_rank in allowed_ranks)
        ]
        matching_ids.sort(key=lambda idx: (hand_of_cards[idx].card_rank.value, idx))
        return matching_ids

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
        for template_name in template_names:
            vision = getattr(vio, template_name, None)
            if vision is None:
                continue
            if find(vision, card.card_image):
                return True
        return False

    def _card_template_name(self, card: Card, template_names: Sequence[str]) -> str | None:
        return next((template_name for template_name in template_names if self._card_matches_any(card, (template_name,))), None)

    def estimate_auto_merge_count_after_play(self, hand_of_cards: list[Card], played_idx: int) -> int:
        if not (0 <= played_idx < len(hand_of_cards)):
            return 0

        simulated_cards = []
        for idx, card in enumerate(hand_of_cards):
            if idx == played_idx or card.card_type in {CardTypes.NONE, CardTypes.GROUND}:
                continue
            template_name = self._card_template_name(card, MERGE_GUARD_TEMPLATES)
            simulated_cards.append({"template_name": template_name, "card_rank": card.card_rank})

        merge_count = 0
        cursor = 0
        while cursor < len(simulated_cards) - 1:
            left_card = simulated_cards[cursor]
            right_card = simulated_cards[cursor + 1]
            if (
                left_card["template_name"] is not None
                and left_card["template_name"] == right_card["template_name"]
                and left_card["card_rank"] == right_card["card_rank"]
                and left_card["card_rank"] in {CardRanks.BRONZE, CardRanks.SILVER}
            ):
                next_rank = CardRanks.SILVER if left_card["card_rank"] == CardRanks.BRONZE else CardRanks.GOLD
                simulated_cards[cursor] = {"template_name": left_card["template_name"], "card_rank": next_rank}
                del simulated_cards[cursor + 1]
                merge_count += 1
                cursor = max(0, cursor - 1)
                continue
            cursor += 1

        return merge_count
