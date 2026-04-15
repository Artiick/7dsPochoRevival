import time
from collections.abc import Sequence
from numbers import Integral
from typing import Final

import utilities.vision_images as vio
from utilities.card_data import Card, CardRanks, CardTypes
from utilities.fighting_strategies import IBattleStrategy, SmarterBattleStrategy
from utilities.utilities import capture_window, find

P3_EVASION_WAIT_SECONDS: Final[float] = 5.5

_CARD_INFO: Final[tuple[tuple[str, str, str], ...]] = (
    ("jin_st", "indura_jin_st", "melee"),
    ("jin_aoe", "indura_jin_aoe", "ranged"),
    ("roxy_att", "indura_roxy_att", "melee"),
    ("roxy_aoe", "indura_roxy_aoe", "ranged"),
    ("sho_att", "indura_sho_att", "melee"),
    ("sho_aoe", "indura_sho_aoe", "ranged"),
    ("freyr_att", "indura_freyr_att", "ranged"),
    ("freyr_aoe", "indura_freyr_aoe", "ranged"),
    ("freyr_ult", "indura_freyr_ult", "ult"),
    ("ban_att", "indura_ban_att", "ranged"),
    ("ban_aoe", "indura_ban_aoe", "ranged"),
)

_CARD_TEMPLATE_BY_KEY: Final[dict[str, object]] = {
    key: getattr(vio, template_name) for key, template_name, _ in _CARD_INFO
}
_CARD_LABEL_BY_KEY: Final[dict[str, str]] = {
    "jin_st": "jinwoo st",
    "jin_aoe": "jinwoo aoe",
    "roxy_att": "roxy att",
    "roxy_aoe": "roxy aoe",
    "sho_att": "sho att",
    "sho_aoe": "sho aoe",
    "freyr_att": "freyr att",
    "freyr_aoe": "freyr aoe",
    "freyr_ult": "freyr ult",
    "ban_att": "ban att",
    "ban_aoe": "ban aoe",
}
_RANK_LABEL: Final[dict[int, str]] = {
    CardRanks.BRONZE.value: "bronze",
    CardRanks.SILVER.value: "silver",
    CardRanks.GOLD.value: "gold",
    CardRanks.ULTIMATE.value: "ult-tier",
}

_FREYR_CLEANSE_KEYS: Final[tuple[str, ...]] = ("freyr_att", "freyr_ult")
_FREYR_CLEANSE_PRIORITY: Final[tuple[str, ...]] = ("freyr_att", "freyr_ult")
_FREYR_FALLBACK_PRIORITY: Final[tuple[str, ...]] = ("freyr_att", "freyr_ult", "freyr_aoe")
_BAN_KEYS: Final[tuple[str, ...]] = ("ban_att", "ban_aoe")
_MELEE_KEYS: Final[tuple[str, ...]] = ("jin_st", "roxy_att", "sho_att")
_RANGED_KEYS: Final[tuple[str, ...]] = (
    "jin_aoe",
    "roxy_aoe",
    "sho_aoe",
    "freyr_att",
    "freyr_aoe",
    "ban_att",
    "ban_aoe",
)


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
        phase_turn = IBattleStrategy.fight_turn - type(self)._p2_entry_fight_turn if phase == 2 else IBattleStrategy.fight_turn
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

        if phase_turn == 0:
            self._disable_card_keys(hand_of_cards, hand_cache, ("ban_aoe",))
            return None

        freyr_att_ids = self._matching_card_ids(hand_of_cards, hand_cache, ("freyr_att",))
        played_freyr_att = self._matching_card_ids(
            picked_cards,
            picked_cache,
            ("freyr_att",),
            include_unplayable=True,
        )
        if freyr_att_ids and find(vio.snake_f3p2_counter, screenshot) and not played_freyr_att:
            preferred = self._matching_card_ids(
                hand_of_cards,
                hand_cache,
                ("freyr_att",),
                ranks=(CardRanks.SILVER, CardRanks.GOLD),
            )
            chosen = (preferred or freyr_att_ids)[-1]
            print("[HumanTeam] Counter present - absorbing with freyr att")
            return self._play(chosen, hand_of_cards, hand_cache)

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
        if find(vio.block_skill_debuf, screenshot):
            already_cleansed = self._matching_card_ids(
                picked_cards,
                picked_cache,
                _FREYR_CLEANSE_KEYS,
                include_unplayable=True,
            )
            cleanse_id = self._best_freyr_id(hand_of_cards, hand_cache, _FREYR_CLEANSE_PRIORITY)
            if cleanse_id is not None and not already_cleansed:
                print("[HumanTeam] Card-seal debuff (P2) - using freyr cleanse")
                return self._play(cleanse_id, hand_of_cards, hand_cache)

        if phase_turn == 0:
            ban_ids = self._matching_card_ids(hand_of_cards, hand_cache, _BAN_KEYS)
            ban_id = ban_ids[-1] if ban_ids else None
            if ban_id is not None:
                print("[HumanTeam] P2 turn 0 - using Ban fallback")
                return self._play(ban_id, hand_of_cards, hand_cache)
        else:
            if self._matching_card_ids(hand_of_cards, hand_cache, _BAN_KEYS):
                print("[HumanTeam] P2 later turn - suppressing Ban cards before fallback")
                self._disable_card_keys(hand_of_cards, hand_cache, _BAN_KEYS)

        return None

    def _get_next_card_index_phase3(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        screenshot,
        hand_cache: dict[str, object],
        picked_cache: dict[str, object],
        *,
        card_turn: int,
    ) -> int | None:
        melee_evasion_up = find(vio.melee_evasion, screenshot)
        ranged_evasion_up = find(vio.ranged_evasion, screenshot)
        has_evasion = melee_evasion_up or ranged_evasion_up
        evasion_passable_only = False

        if has_evasion:
            played_ult_this_turn = any(card.card_type == CardTypes.ULTIMATE for card in picked_cards)
            if not played_ult_this_turn:
                ult_ids = self._sorted_indices(
                    [idx for idx, card in enumerate(hand_of_cards) if card.card_type == CardTypes.ULTIMATE],
                    hand_of_cards,
                )
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

        if find(vio.block_skill_debuf, screenshot):
            already_cleansed = self._matching_card_ids(
                picked_cards,
                picked_cache,
                _FREYR_CLEANSE_KEYS,
                include_unplayable=True,
            )
            cleanse_id = self._best_freyr_id(hand_of_cards, hand_cache, _FREYR_CLEANSE_PRIORITY)
            if cleanse_id is not None and not already_cleansed:
                print("[HumanTeam] Card-seal debuff (P3) - using freyr cleanse")
                return self._play(cleanse_id, hand_of_cards, hand_cache)

        if evasion_passable_only and has_evasion:
            if melee_evasion_up:
                passable = self._attack_mode_ids(hand_of_cards, hand_cache, _RANGED_KEYS)
                passable += [idx for idx, card in enumerate(hand_of_cards) if card.card_type == CardTypes.ULTIMATE]
                passable = self._sorted_indices(list(dict.fromkeys(passable)), hand_of_cards)
                print(f"[HumanTeam] Melee evasion active - ranged/ult only ({len(passable)} options)")
            else:
                passable = self._attack_mode_ids(hand_of_cards, hand_cache, _MELEE_KEYS)
                passable += [idx for idx, card in enumerate(hand_of_cards) if card.card_type == CardTypes.ULTIMATE]
                freyr_att_ids = self._matching_card_ids(hand_of_cards, hand_cache, ("freyr_att",))
                if freyr_att_ids:
                    print(
                        "[HumanTeam] Ranged evasion active - freyr att included for cleanse "
                        "(attack evaded, cleanse still fires)"
                    )
                passable += freyr_att_ids
                passable = self._sorted_indices(list(dict.fromkeys(passable)), hand_of_cards)
                print(f"[HumanTeam] Ranged evasion active - melee/ult/freyr-att ({len(passable)} options)")

            if passable:
                return self._play(passable[-1], hand_of_cards, hand_cache)

            fallback_id = self._best_freyr_id(hand_of_cards, hand_cache, _FREYR_FALLBACK_PRIORITY)
            if fallback_id is not None:
                print("[HumanTeam] Evasion: no passable cards - using freyr fallback")
                return self._play(fallback_id, hand_of_cards, hand_cache)

        return None

    def _common_fallback(
        self,
        hand_of_cards: list[Card],
        picked_cards: list[Card],
        hand_cache: dict[str, object],
    ) -> int:
        self._deprioritize_freyr_aoe(hand_of_cards, hand_cache)

        print("[HumanTeam] No special override - delegating to SmarterBattleStrategy")
        idx = SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)
        if isinstance(idx, Integral):
            return self._play(idx, hand_of_cards, hand_cache)
        print(f"[HumanTeam] >> Delegating move {idx}")
        return idx

    def _disable_card_keys(
        self,
        hand_of_cards: list[Card],
        hand_cache: dict[str, object],
        card_keys: Sequence[str],
    ) -> None:
        for idx in self._matching_card_ids(hand_of_cards, hand_cache, card_keys):
            hand_of_cards[idx].card_type = CardTypes.DISABLED

    def _deprioritize_freyr_aoe(self, hand_of_cards: list[Card], hand_cache: dict[str, object]) -> None:
        freyr_aoe_ids = self._matching_card_ids(hand_of_cards, hand_cache, ("freyr_aoe",))
        if not freyr_aoe_ids:
            return

        other_playable_exists = any(
            idx not in freyr_aoe_ids and card.card_type not in (CardTypes.DISABLED, CardTypes.NONE, CardTypes.GROUND)
            for idx, card in enumerate(hand_of_cards)
        )
        if not other_playable_exists:
            return

        for idx in freyr_aoe_ids:
            hand_of_cards[idx].card_type = CardTypes.DISABLED
        print("[HumanTeam] Deprioritizing freyr aoe while better playable cards exist")

    def _best_freyr_id(
        self,
        hand_of_cards: list[Card],
        hand_cache: dict[str, object],
        priority_keys: Sequence[str],
    ) -> int | None:
        for key in priority_keys:
            ids = self._matching_card_ids(hand_of_cards, hand_cache, (key,))
            if ids:
                return ids[-1]
        return None

    def _play(self, idx: int, hand_of_cards: list[Card], hand_cache: dict[str, object]) -> int:
        label = self._card_label(hand_of_cards[idx], card_key=self._card_key_from_cache(hand_cache, idx))
        print(f"[HumanTeam] >> Playing {label}")
        return idx

    def _card_label(self, card: Card, *, card_key: str | None = None) -> str:
        rank_str = _RANK_LABEL.get(card.card_rank.value, "?")
        if card_key is None:
            return f"{rank_str} {card.card_type.name.lower()}"
        if card_key in _CARD_LABEL_BY_KEY:
            return f"{rank_str} {_CARD_LABEL_BY_KEY[card_key]}"
        return f"{rank_str} {card.card_type.name.lower()}"

    def _build_hand_cache(self, cards: Sequence[Card]) -> dict[str, object]:
        return {
            "cards": cards,
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
        return self._sorted_indices(matching_ids, cards)

    def _attack_mode_ids(
        self,
        cards: Sequence[Card],
        cache: dict[str, object],
        template_keys: Sequence[str],
    ) -> list[int]:
        attackish_types = (CardTypes.ATTACK, CardTypes.ATTACK_DEBUFF)
        ids = [
            idx
            for idx, card in enumerate(cards)
            if card.card_type in attackish_types and self._card_key_from_cache(cache, idx) in template_keys
        ]
        return self._sorted_indices(ids, cards)

    def _sorted_indices(self, ids: Sequence[int], cards: Sequence[Card]) -> list[int]:
        return sorted(ids, key=lambda idx: (cards[idx].card_rank.value, idx))
