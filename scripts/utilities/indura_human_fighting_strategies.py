import time
from collections.abc import Sequence
from numbers import Integral
from typing import Final

import numpy as np
import utilities.vision_images as vio
from utilities.card_data import Card, CardRanks, CardTypes
from utilities.coordinates import Coordinates
from utilities.fighting_strategies import IBattleStrategy, SmarterBattleStrategy
from utilities.utilities import capture_window, crop_region, find

P3_EVASION_WAIT_SECONDS: Final[float] = 5.5

_CARD_INFO: Final[tuple[tuple[str, str, str, str], ...]] = (
    ("jin_st", "indura_jin_st", "jinwoo st", "melee"),
    ("jin_aoe", "indura_jin_aoe", "jinwoo aoe", "ranged"),
    ("jin_ult", "indura_jin_ult", "jinwoo ult", "ult"),
    ("roxy_att", "indura_roxy_att", "roxy att", "melee"),
    ("roxy_aoe", "indura_roxy_aoe", "roxy aoe", "ranged"),
    ("roxy_ult", "indura_roxy_ult", "roxy ult", "ult"),
    ("sho_att", "indura_sho_att", "sho att", "melee"),
    ("sho_aoe", "indura_sho_aoe", "sho aoe", "ranged"),
    ("sho_ult", "indura_sho_ult", "sho ult", "ult"),
    ("freyr_att", "indura_freyr_att", "freyr att", "ranged"),
    ("freyr_aoe", "indura_freyr_aoe", "freyr aoe", "ranged"),
    ("freyr_ult", "indura_freyr_ult", "freyr ult", "ult"),
    ("ban_att", "indura_ban_att", "ban att", "ranged"),
    ("ban_aoe", "indura_ban_aoe", "ban aoe", "ranged"),
    ("ban_ult", "indura_ban_ult", "ban ult", "ult"),
    ("mikasa_att", "indura_mikasa_att", "mikasa att", "melee"),
    ("mikasa_debuff", "indura_mikasa_debuff", "mikasa debuff", "melee"),
    ("mikasa_ult", "indura_mikasa_ult", "mikasa ult", "ult"),
)

_GROUP_TEMPLATES: Final[dict[str, tuple[str, ...]]] = {
    "freyr": ("freyr_att", "freyr_aoe", "freyr_ult"),
    "freyr_cleanse": ("freyr_att", "freyr_ult"),
    "ban": ("ban_att", "ban_aoe", "ban_ult"),
    "priority_ult": ("roxy_ult", "sho_ult"),
    "melee": tuple(key for key, _, _, attack_type in _CARD_INFO if attack_type == "melee"),
    "ranged": tuple(key for key, _, _, attack_type in _CARD_INFO if attack_type == "ranged"),
}

_RANK_LABEL: Final[dict[int, str]] = {
    CardRanks.BRONZE.value: "bronze",
    CardRanks.SILVER.value: "silver",
    CardRanks.GOLD.value: "gold",
    CardRanks.ULTIMATE.value: "ult-tier",
}

_CARD_TEMPLATE_BY_KEY: Final[dict[str, object]] = {
    key: getattr(vio, template_name) for key, template_name, _, _ in _CARD_INFO
}
_CARD_NAME_BY_KEY: Final[dict[str, str]] = {key: display_name for key, _, display_name, _ in _CARD_INFO}
_CARD_ATTACK_TYPE_BY_KEY: Final[dict[str, str]] = {key: attack_type for key, _, _, attack_type in _CARD_INFO}


class InduraHumanBattleStrategy(IBattleStrategy):
    """Battle strategy for the Human-team Indura Death Match."""

    _p2_entry_fight_turn: int = -1

    def get_next_card_index(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        phase: int = 1,
        card_turn: int = 0,
        **kwargs,
    ) -> int:
        screenshot, _ = capture_window()
        hand_cache = self._build_hand_cache(hand_of_cards)
        picked_cache = self._build_hand_cache(picked_cards)

        self._update_phase_2_entry_fight_turn(phase)
        phase_turn = self._phase_turn(phase)
        print(f"[HumanTeam] phase={phase}  phase_turn={phase_turn}  card_turn={card_turn}")

        if phase == 1:
            result = self._get_next_card_index_phase1(
                hand_of_cards,
                picked_cards,
                screenshot,
                hand_cache,
                picked_cache,
                phase_turn=phase_turn,
            )
        elif phase == 2:
            result = self._get_next_card_index_phase2(
                hand_of_cards,
                picked_cards,
                screenshot,
                hand_cache,
                picked_cache,
                phase_turn=phase_turn,
            )
        elif phase == 3:
            result = self._get_next_card_index_phase3(
                hand_of_cards,
                picked_cards,
                screenshot,
                hand_cache,
                picked_cache,
                phase_turn=phase_turn,
                card_turn=card_turn,
            )
        else:
            result = None

        if result is not None:
            return result

        return self._common_fallback(hand_of_cards, picked_cards, hand_cache)

    def _update_phase_2_entry_fight_turn(self, phase: int) -> None:
        if phase == 2 and type(self)._p2_entry_fight_turn == -1:
            type(self)._p2_entry_fight_turn = IBattleStrategy.fight_turn
            print(f"[HumanTeam] Entered phase 2 at fight turn {IBattleStrategy.fight_turn}")
        elif phase != 2:
            type(self)._p2_entry_fight_turn = -1

    def _phase_turn(self, phase: int) -> int:
        if phase == 2:
            return IBattleStrategy.fight_turn - type(self)._p2_entry_fight_turn
        return IBattleStrategy.fight_turn

    def _get_next_card_index_phase1(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        screenshot,
        hand_cache: dict[str, object],
        picked_cache: dict[str, object],
        *,
        phase_turn: int,
    ) -> int | None:
        type(self)._p2_entry_fight_turn = -1

        freyr_ids = self._matching_card_ids(hand_of_cards, hand_cache, _GROUP_TEMPLATES["freyr"])
        freyr_att_ids = self._matching_card_ids(hand_of_cards, hand_cache, ("freyr_att",))
        ban_aoe_ids = self._matching_card_ids(hand_of_cards, hand_cache, ("ban_aoe",))
        ult_ids = self._ultimate_ids(hand_of_cards, hand_cache)

        if phase_turn == 0:
            for idx in freyr_ids + ban_aoe_ids:
                hand_of_cards[idx].card_type = CardTypes.DISABLED
        else:
            played_freyr_att = self._played_matching_card_ids(picked_cards, picked_cache, ("freyr_att",))
            if freyr_att_ids and find(vio.snake_f3p2_counter, screenshot) and not played_freyr_att:
                preferred = [idx for idx in freyr_att_ids if hand_cache["card_ranks"][idx] >= CardRanks.SILVER.value]
                chosen = (preferred or freyr_att_ids)[-1]
                print("[HumanTeam] Counter present - absorbing with freyr att")
                return self._play(chosen, hand_of_cards, hand_cache)

            for idx in freyr_att_ids:
                hand_of_cards[idx].card_type = CardTypes.DISABLED

        if ult_ids:
            return self._play(ult_ids[-1], hand_of_cards, hand_cache)

        return None

    def _get_next_card_index_phase2(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        screenshot,
        hand_cache: dict[str, object],
        picked_cache: dict[str, object],
        *,
        phase_turn: int,
    ) -> int | None:
        freyr_cleanse_ids = self._matching_card_ids(hand_of_cards, hand_cache, _GROUP_TEMPLATES["freyr_cleanse"])
        freyr_ids = self._matching_card_ids(hand_of_cards, hand_cache, _GROUP_TEMPLATES["freyr"])
        freyr_att_ids = self._matching_card_ids(hand_of_cards, hand_cache, ("freyr_att",))
        ban_ids = self._matching_card_ids(hand_of_cards, hand_cache, _GROUP_TEMPLATES["ban"])
        ult_ids = self._ultimate_ids(hand_of_cards, hand_cache)
        held_ult_ids = list(ult_ids)
        for idx in held_ult_ids:
            hand_of_cards[idx].card_type = CardTypes.DISABLED

        if find(vio.block_skill_debuf, screenshot):
            already_cleansed = self._played_matching_card_ids(picked_cards, picked_cache, _GROUP_TEMPLATES["freyr"])
            if freyr_cleanse_ids and not already_cleansed:
                print("[HumanTeam] Card-seal debuff (P2) - using freyr cleanse")
                return self._play(freyr_cleanse_ids[-1], hand_of_cards, hand_cache)

        if phase_turn == 0:
            six_slots = crop_region(screenshot, Coordinates.get_coordinates("6_cards_region"))
            ally_has_cleanse = find(vio.mini_king, six_slots) or any(
                find(template, six_slots)
                for template in (vio.indura_freyr_att, vio.indura_freyr_ult)
            )
            if ally_has_cleanse:
                print("[HumanTeam] P2 turn 0 - ally cleanse (King or Freyr) detected in played slots")

            if freyr_att_ids:
                print("[HumanTeam] P2 turn 0 - playing freyr att (passive + Sho cleanse)")
                return self._play(freyr_att_ids[-1], hand_of_cards, hand_cache)
            if freyr_ids:
                print("[HumanTeam] P2 turn 0 - playing freyr card (passive + cleanse)")
                return self._play(freyr_ids[-1], hand_of_cards, hand_cache)

            if ally_has_cleanse:
                print("[HumanTeam] P2 turn 0 - no freyr; ally handling Sho cleanse")
            else:
                print("[HumanTeam] P2 turn 0 - no freyr on team; no ally cleanse detected")

            if ban_ids:
                return self._play(ban_ids[-1], hand_of_cards, hand_cache)
        else:
            for idx in ban_ids:
                hand_of_cards[idx].card_type = CardTypes.DISABLED

        attack_ids = self._attack_ids(hand_of_cards, hand_cache)
        if attack_ids:
            return self._play(attack_ids[-1], hand_of_cards, hand_cache)

        for idx in held_ult_ids:
            hand_of_cards[idx].card_type = CardTypes.ULTIMATE
        live_ults = self._ultimate_ids(hand_of_cards, hand_cache)
        if live_ults:
            print("[HumanTeam] P2 last resort - releasing held ults")
            return self._play(live_ults[-1], hand_of_cards, hand_cache)

        return None

    def _get_next_card_index_phase3(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        screenshot,
        hand_cache: dict[str, object],
        picked_cache: dict[str, object],
        *,
        phase_turn: int,
        card_turn: int,
    ) -> int | None:
        freyr_ids = self._matching_card_ids(hand_of_cards, hand_cache, _GROUP_TEMPLATES["freyr"])
        melee_evasion_up = find(vio.melee_evasion, screenshot)
        ranged_evasion_up = find(vio.ranged_evasion, screenshot)
        has_evasion = melee_evasion_up or ranged_evasion_up
        evasion_passable_only = False

        ult_ids = self._ultimate_ids(hand_of_cards, hand_cache)
        if has_evasion:
            played_ult_this_turn = any(card.card_type == CardTypes.ULTIMATE for card in picked_cards)
            if not played_ult_this_turn:
                if ult_ids:
                    evasion_type = "melee" if melee_evasion_up else "ranged"
                    print(f"[HumanTeam] P3 {evasion_type} evasion - forcing ult to clear it")
                    return self._play(ult_ids[-1], hand_of_cards, hand_cache)

                if card_turn == 0:
                    print(f"[HumanTeam] P3 evasion: no ult - waiting {P3_EVASION_WAIT_SECONDS}s to observe ally...")
                    time.sleep(P3_EVASION_WAIT_SECONDS)
                    screenshot, _ = capture_window()
                    melee_evasion_up = find(vio.melee_evasion, screenshot)
                    ranged_evasion_up = find(vio.ranged_evasion, screenshot)
                    has_evasion = melee_evasion_up or ranged_evasion_up
                    if not has_evasion:
                        print("[HumanTeam] Ally cleared the evasion - proceeding normally!")
                    else:
                        print("[HumanTeam] Evasion still present after wait - filtering to passable cards")
                        evasion_passable_only = True
                else:
                    evasion_passable_only = True

        freyr_cleanse_ids = self._matching_card_ids(hand_of_cards, hand_cache, _GROUP_TEMPLATES["freyr_cleanse"])
        if find(vio.block_skill_debuf, screenshot):
            already_cleansed = self._played_matching_card_ids(picked_cards, picked_cache, _GROUP_TEMPLATES["freyr"])
            if freyr_cleanse_ids and not already_cleansed:
                print("[HumanTeam] Card-seal debuff (P3) - using freyr cleanse")
                return self._play(freyr_cleanse_ids[-1], hand_of_cards, hand_cache)

        if phase_turn == 0:
            for idx in ult_ids:
                hand_of_cards[idx].card_type = CardTypes.DISABLED
        else:
            priority_ults = self._matching_card_ids(hand_of_cards, hand_cache, _GROUP_TEMPLATES["priority_ult"])
            priority_ults = [idx for idx in priority_ults if hand_of_cards[idx].card_type == CardTypes.ULTIMATE]
            if priority_ults:
                print("[HumanTeam] P3 - using priority ult (roxy/sho)")
                return self._play(priority_ults[-1], hand_of_cards, hand_cache)
            if ult_ids:
                return self._play(ult_ids[-1], hand_of_cards, hand_cache)

        if evasion_passable_only and has_evasion:
            if melee_evasion_up:
                passable = self._matching_card_ids(hand_of_cards, hand_cache, _GROUP_TEMPLATES["ranged"])
                passable += self._ultimate_ids(hand_of_cards, hand_cache)
                passable = self._dedupe_sorted_ids(passable, hand_cache["card_ranks"])
                print(f"[HumanTeam] Melee evasion active - ranged/ult only ({len(passable)} options)")
            else:
                freyr_att_through_evasion = self._matching_card_ids(hand_of_cards, hand_cache, ("freyr_att",))
                if freyr_att_through_evasion:
                    print(
                        "[HumanTeam] Ranged evasion active - freyr att included for cleanse "
                        "(attack evaded, cleanse still fires)"
                    )
                passable = self._matching_card_ids(hand_of_cards, hand_cache, _GROUP_TEMPLATES["melee"])
                passable += self._ultimate_ids(hand_of_cards, hand_cache)
                passable += freyr_att_through_evasion
                passable = self._dedupe_sorted_ids(passable, hand_cache["card_ranks"])
                print(f"[HumanTeam] Ranged evasion active - melee/ult/freyr-att ({len(passable)} options)")

            if passable:
                return self._play(passable[-1], hand_of_cards, hand_cache)

            if freyr_ids:
                print("[HumanTeam] Evasion: no passable cards - tossing freyr card to cycle hand")
                return self._play(freyr_ids[-1], hand_of_cards, hand_cache)

        return None

    def _common_fallback(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        hand_cache: dict[str, object],
    ) -> int:
        attack_ids = self._attack_ids(hand_of_cards, hand_cache)
        if attack_ids:
            return self._play(attack_ids[-1], hand_of_cards, hand_cache)

        print("[HumanTeam] No suitable card found - delegating to SmarterBattleStrategy")
        idx = SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)
        if isinstance(idx, Integral):
            return self._play(idx, hand_of_cards, hand_cache)
        print(f"[HumanTeam] >> Delegating move {idx}")
        return idx

    def _play(self, idx: int, hand_of_cards: list[Card], hand_cache: dict[str, object]) -> int:
        label = self._card_label(
            hand_of_cards[idx],
            int(hand_cache["card_ranks"][idx]),
            card_key=self._card_key_from_cache(hand_cache, idx),
        )
        print(f"[HumanTeam] >> Playing {label}")
        return idx

    def _card_label(self, card: Card, rank_value: int, *, card_key: str | None = None) -> str:
        rank_str = _RANK_LABEL.get(rank_value, "?")
        if card_key is None:
            card_key = self._card_key(card)
        if card_key is None:
            return f"{rank_str} {card.card_type.name.lower()} [unknown]"
        return f"{rank_str} {_CARD_NAME_BY_KEY[card_key]} [{_CARD_ATTACK_TYPE_BY_KEY[card_key]}]"

    def _build_hand_cache(self, cards: Sequence[Card]) -> dict[str, object]:
        card_ranks = np.array([card.card_rank.value for card in cards])
        return {
            "cards": cards,
            "card_ranks": card_ranks,
            "card_keys": [None] * len(cards),
        }

    def _card_key(self, card: Card) -> str | None:
        if card.card_image is None:
            return None
        for key, template in _CARD_TEMPLATE_BY_KEY.items():
            if find(template, card.card_image):
                return key
        return None

    def _card_key_from_cache(self, cache: dict[str, object], idx: int) -> str | None:
        card_key = cache["card_keys"][idx]
        if card_key is None and cache["cards"][idx].card_image is not None:
            card_key = self._card_key(cache["cards"][idx])
            cache["card_keys"][idx] = card_key
        return card_key

    def _matching_card_ids(
        self,
        cards: Sequence[Card],
        cache: dict[str, object],
        template_keys: Sequence[str],
        *,
        ranks: Sequence[CardRanks] | None = None,
        include_unplayable: bool = False,
    ) -> list[int]:
        allowed_ranks = frozenset(ranks) if ranks is not None else None
        blocked_types = () if include_unplayable else (CardTypes.DISABLED, CardTypes.NONE, CardTypes.GROUND)
        matching_ids = [
            idx
            for idx, card in enumerate(cards)
            if card.card_type not in blocked_types
            and self._card_key_from_cache(cache, idx) in template_keys
            and (allowed_ranks is None or card.card_rank in allowed_ranks)
        ]
        return self._sorted_indices(matching_ids, cache["card_ranks"])

    def _played_matching_card_ids(
        self,
        cards: Sequence[Card],
        cache: dict[str, object],
        template_keys: Sequence[str],
    ) -> list[int]:
        return self._matching_card_ids(cards, cache, template_keys, include_unplayable=True)

    def _attack_ids(self, cards: Sequence[Card], cache: dict[str, object]) -> list[int]:
        attack_ids = [
            idx
            for idx, card in enumerate(cards)
            if card.card_type == CardTypes.ATTACK
        ]
        return self._sorted_indices(attack_ids, cache["card_ranks"])

    def _ultimate_ids(self, cards: Sequence[Card], cache: dict[str, object]) -> list[int]:
        ult_ids = [
            idx
            for idx, card in enumerate(cards)
            if card.card_type == CardTypes.ULTIMATE
        ]
        return self._sorted_indices(ult_ids, cache["card_ranks"])

    def _dedupe_sorted_ids(self, ids: Sequence[int], card_ranks: np.ndarray) -> list[int]:
        return self._sorted_indices(list(dict.fromkeys(ids)), card_ranks)

    def _sorted_indices(self, ids: Sequence[int], card_ranks: np.ndarray) -> list[int]:
        return sorted(ids, key=lambda idx: (card_ranks[idx], idx))
