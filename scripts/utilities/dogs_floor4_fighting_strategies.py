from collections.abc import Sequence
from enum import Enum
from typing import Final

import utilities.vision_images as vio
from utilities.card_data import Card, CardRanks, CardTypes
from utilities.fighting_strategies import IBattleStrategy, SmarterBattleStrategy
from utilities.utilities import capture_window, crop_image, find


class DogsFloor4Phase3State(Enum):
    STALL_FOR_GAUGE = "STALL_FOR_GAUGE"
    TRIGGER_GIMMICK_1 = "TRIGGER_GIMMICK_1"
    KILL_BOTH_DOGS = "KILL_BOTH_DOGS"


class Phase3GimmickStep(Enum):
    """Ordered gimmick-turn plays after Escalin talent (playbook: optional nasi, gold R/L, escalin ult; STs follow in kill)."""

    OPENING_AFTER_TALENT = "OPENING_AFTER_TALENT"
    GOLD_RIGHT = "GOLD_RIGHT"
    GOLD_LEFT = "GOLD_LEFT"
    ESCALIN_ULT = "ESCALIN_ULT"
    COMPLETE = "COMPLETE"


# Phase 3 orb model / crops (module-level; vision hook uses PHASE3_ORB_SOURCE).
# Allowed PHASE3_ORB_SOURCE values: "stub_never_ready", "stub_always_three", "lite_progress"; unknown -> stub_never_ready behavior.
PHASE3_ORB_SOURCE: Final[str] = "stub_never_ready"
PHASE3_MAX_DOG_GAUGE: Final[int] = 7
PHASE3_GAUGE_DISPARITY_THRESHOLD: Final[int] = 2
PHASE3_LEFT_TOP_LEFT: Final[tuple[int, int]] = (70, 210)
PHASE3_LEFT_BOTTOM_RIGHT: Final[tuple[int, int]] = (220, 320)
PHASE3_RIGHT_TOP_LEFT: Final[tuple[int, int]] = (260, 210)
PHASE3_RIGHT_BOTTOM_RIGHT: Final[tuple[int, int]] = (400, 320)

ESCALIN_TEMPLATES: Final[tuple[str, ...]] = ("escalin_st", "escalin_aoe", "escalin_ult")
ROXY_TEMPLATES: Final[tuple[str, ...]] = ("roxy_st", "roxy_aoe", "roxy_ult")
ROXY_NON_ULT_TEMPLATES: Final[tuple[str, ...]] = ("roxy_st", "roxy_aoe")
NASI_TEMPLATES: Final[tuple[str, ...]] = ("nasi_heal", "nasi_stun", "nasi_ult")
NASI_NON_ULT_TEMPLATES: Final[tuple[str, ...]] = ("nasi_heal", "nasi_stun")
THONAR_TEMPLATES: Final[tuple[str, ...]] = ("thonar_stance", "thonar_gauge", "thonar_ult")


class DogsFloor4BattleStrategy(IBattleStrategy):
    """Scripted Dogs Floor 4 strategy.

    Phase 1, Phase 2, and Phase 3 are implemented.
    """

    turn = 0
    _phase_initialized = set()
    _last_phase_seen = None
    # Inert unless a fighter checks it before phase 3 (not implemented on minimal DogsFloor4Fighter).
    stop_after_phase_2 = False
    p2_stall_turns_used = 0
    _p2_stall_increment_pending = False
    phase2_use_talent_before_next_play = False
    phase3_state = DogsFloor4Phase3State.STALL_FOR_GAUGE
    phase3_dog_orbs = {"left": 0, "right": 0}
    phase3_pending_gauge_reset = {"left": False, "right": False}
    phase3_gimmick1_completed = False
    phase3_trigger_turn_active = False
    phase3_trigger_gauge_targets_used = set()
    phase3_observed_turn = None
    phase3_next_target_side = None
    phase3_use_talent_before_next_play = False
    phase3_gimmick_step = Phase3GimmickStep.OPENING_AFTER_TALENT
    phase3_detected_stage_turn = None
    phase3_kill_next_st_side = "left"

    def _initialize_static_variables(self):
        DogsFloor4BattleStrategy.turn = 0
        DogsFloor4BattleStrategy._phase_initialized = set()
        DogsFloor4BattleStrategy._last_phase_seen = None
        DogsFloor4BattleStrategy.p2_stall_turns_used = 0
        DogsFloor4BattleStrategy._p2_stall_increment_pending = False
        DogsFloor4BattleStrategy.phase2_use_talent_before_next_play = False
        DogsFloor4BattleStrategy._reset_phase3_state()

    @classmethod
    def _reset_phase3_state(cls):
        cls.phase3_state = DogsFloor4Phase3State.STALL_FOR_GAUGE
        cls.phase3_dog_orbs = {"left": 0, "right": 0}
        cls.phase3_pending_gauge_reset = {"left": False, "right": False}
        cls.phase3_gimmick1_completed = False
        cls.phase3_trigger_turn_active = False
        cls.phase3_trigger_gauge_targets_used = set()
        cls.phase3_observed_turn = None
        cls.phase3_next_target_side = None
        cls.phase3_use_talent_before_next_play = False
        cls.phase3_gimmick_step = Phase3GimmickStep.OPENING_AFTER_TALENT
        cls.phase3_detected_stage_turn = None
        cls.phase3_kill_next_st_side = "left"

    def reset_run_state(self):
        self._initialize_static_variables()

    def on_player_turn_completed(self, phase: int | None) -> None:
        """Called by DogsFighter.finish_turn before IBattleStrategy.increment_fight_turn (no fighter imports here)."""
        if phase == 3:
            self.handle_phase3_turn_end()
        if DogsFloor4BattleStrategy._last_phase_seen == 2 and DogsFloor4BattleStrategy._p2_stall_increment_pending:
            DogsFloor4BattleStrategy.p2_stall_turns_used += 1
        DogsFloor4BattleStrategy._p2_stall_increment_pending = False
        DogsFloor4BattleStrategy.turn += 1

    def get_next_card_index(
        self, hand_of_cards: list[Card], picked_cards: list[Card], phase: int, card_turn=0, **kwargs
    ) -> int:
        """Return the next scripted action for Dogs Floor 4."""

        if phase == 1 and DogsFloor4BattleStrategy._last_phase_seen != 1:
            self._initialize_static_variables()

        DogsFloor4BattleStrategy._last_phase_seen = phase

        if phase == 1:
            return self.get_next_card_index_phase1(hand_of_cards, picked_cards, card_turn=card_turn)
        if phase == 2:
            return self.get_next_card_index_phase2(hand_of_cards, picked_cards, card_turn=card_turn)

        return self.get_next_card_index_phase3(hand_of_cards, picked_cards, card_turn=card_turn)

    def _maybe_reset(self, phase_id: str):
        if phase_id not in DogsFloor4BattleStrategy._phase_initialized:
            DogsFloor4BattleStrategy.turn = 0
            DogsFloor4BattleStrategy._phase_initialized.add(phase_id)
            if phase_id == "phase_2":
                DogsFloor4BattleStrategy.p2_stall_turns_used = 0
                DogsFloor4BattleStrategy._p2_stall_increment_pending = False
                DogsFloor4BattleStrategy.phase2_use_talent_before_next_play = False
            elif phase_id == "phase_3":
                DogsFloor4BattleStrategy._reset_phase3_state()

    def get_next_card_index_phase1(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_1")

        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def get_next_card_index_phase2(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_2")

        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def get_next_card_index_phase3(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        self._maybe_reset("phase_3")

        DogsFloor4BattleStrategy.phase3_use_talent_before_next_play = False
        DogsFloor4BattleStrategy.phase3_next_target_side = None

        if card_turn == 0:
            screenshot, _ = capture_window()
            self._observe_phase3_turn_start(screenshot, hand_of_cards)
            print(
                "Phase 3 start-of-turn context -> "
                f"state={DogsFloor4BattleStrategy.phase3_state.value}, "
                f"gauges={DogsFloor4BattleStrategy.phase3_dog_orbs}, "
                f"orb_source={PHASE3_ORB_SOURCE!r}"
            )

        if card_turn == 0 and DogsFloor4BattleStrategy.phase3_state != DogsFloor4Phase3State.TRIGGER_GIMMICK_1:
            nasi_ult = self._best_matching_card(hand_of_cards, ("nasi_ult",))
            if nasi_ult != -1:
                print("Phase 3 priority: nasi_ult is available, so using it as the first card.")
                return nasi_ult

        if DogsFloor4BattleStrategy.phase3_state == DogsFloor4Phase3State.STALL_FOR_GAUGE:
            action = self._phase3_stall_action(hand_of_cards, picked_cards, card_turn)
        elif DogsFloor4BattleStrategy.phase3_state == DogsFloor4Phase3State.TRIGGER_GIMMICK_1:
            action = self._phase3_gimmick_action(hand_of_cards, picked_cards, card_turn)
        else:
            action = self._phase3_kill_action(hand_of_cards, picked_cards, card_turn)

        return action

    def _observe_phase3_turn_start(self, screenshot, hand_of_cards: list[Card]):
        if DogsFloor4BattleStrategy.phase3_observed_turn == DogsFloor4BattleStrategy.turn:
            return

        stage_turn_hint = 3 if find(vio.talent_escalin, screenshot, threshold=0.75) else None
        DogsFloor4BattleStrategy.phase3_detected_stage_turn = stage_turn_hint
        if stage_turn_hint is not None:
            print(f"Phase 3 stage hint (talent_escalin) -> {stage_turn_hint}.")

        base = dict(DogsFloor4BattleStrategy.phase3_dog_orbs)
        reset_applied = {"left": False, "right": False}
        for side in ("left", "right"):
            if DogsFloor4BattleStrategy.phase3_pending_gauge_reset[side]:
                base[side] = 0
                DogsFloor4BattleStrategy.phase3_pending_gauge_reset[side] = False
                reset_applied[side] = True

        left_region = crop_image(
            screenshot,
            PHASE3_LEFT_TOP_LEFT,
            PHASE3_LEFT_BOTTOM_RIGHT,
        )
        right_region = crop_image(
            screenshot,
            PHASE3_RIGHT_TOP_LEFT,
            PHASE3_RIGHT_BOTTOM_RIGHT,
        )
        # No dogs_ult vision asset in vio; orb reset from ult markers is disabled until wired.
        left_ult_seen = False
        right_ult_seen = False

        src = PHASE3_ORB_SOURCE
        if src == "stub_always_three":
            gauges = {"left": 3, "right": 3}
        elif src == "lite_progress":
            gauges = {
                "left": min(PHASE3_MAX_DOG_GAUGE, base["left"] + 1),
                "right": min(PHASE3_MAX_DOG_GAUGE, base["right"] + 1),
            }
        elif src == "stub_never_ready":
            gauges = dict(base)
        else:
            print(f"Phase 3: unknown PHASE3_ORB_SOURCE={src!r}; using stub_never_ready behavior.")
            gauges = dict(base)

        DogsFloor4BattleStrategy.phase3_dog_orbs = gauges
        DogsFloor4BattleStrategy.phase3_pending_gauge_reset["left"] = left_ult_seen and not reset_applied["left"]
        DogsFloor4BattleStrategy.phase3_pending_gauge_reset["right"] = right_ult_seen and not reset_applied["right"]
        DogsFloor4BattleStrategy.phase3_observed_turn = DogsFloor4BattleStrategy.turn

        print(
            f"Phase 3 orb observation (source={src!r}) -> gauges={gauges}, "
            f"ult markers left={left_ult_seen}, right={right_ult_seen}"
        )

        self._update_phase3_state(hand_of_cards)

    def _phase3_activate_trigger_state(self):
        DogsFloor4BattleStrategy.phase3_trigger_turn_active = True
        DogsFloor4BattleStrategy.phase3_trigger_gauge_targets_used = set()
        DogsFloor4BattleStrategy.phase3_gimmick_step = Phase3GimmickStep.OPENING_AFTER_TALENT

    def handle_phase3_turn_end(self):
        if not DogsFloor4BattleStrategy.phase3_trigger_turn_active:
            return

        if {"left", "right"}.issubset(DogsFloor4BattleStrategy.phase3_trigger_gauge_targets_used):
            DogsFloor4BattleStrategy.phase3_gimmick1_completed = True
            DogsFloor4BattleStrategy.phase3_state = DogsFloor4Phase3State.KILL_BOTH_DOGS
            print("Phase 3 gimmick 1 completed. Switching to KILL_BOTH_DOGS.")
        else:
            print(
                "Phase 3 trigger turn ended without both gauge removals. "
                f"Observed targets={DogsFloor4BattleStrategy.phase3_trigger_gauge_targets_used}. Returning to stall."
            )
            DogsFloor4BattleStrategy.phase3_state = DogsFloor4Phase3State.STALL_FOR_GAUGE

        DogsFloor4BattleStrategy.phase3_trigger_turn_active = False
        DogsFloor4BattleStrategy.phase3_trigger_gauge_targets_used = set()
        DogsFloor4BattleStrategy.phase3_gimmick_step = Phase3GimmickStep.OPENING_AFTER_TALENT

    def _phase3_transition_decision(self, hand_of_cards: list[Card]) -> tuple[DogsFloor4Phase3State, str, bool]:
        """Compute next macro state for phase 3 from vision + hand.

        Returns (new_state, reason, activate_trigger).
        When activate_trigger is True, caller must call _phase3_activate_trigger_state().
        """
        gauges = DogsFloor4BattleStrategy.phase3_dog_orbs
        both_gauges_ready = gauges["left"] >= 3 and gauges["right"] >= 3
        detected_turn = DogsFloor4BattleStrategy.phase3_detected_stage_turn
        has_thonar_card = bool(self._matching_card_ids(hand_of_cards, THONAR_TEMPLATES))
        gold_gauges = self._thonar_gauge_ids_with_ranks(hand_of_cards, {CardRanks.GOLD})
        gold_gauges_ready = len(gold_gauges) >= 2

        if DogsFloor4BattleStrategy.phase3_gimmick1_completed:
            return DogsFloor4Phase3State.KILL_BOTH_DOGS, "gimmick 1 already completed", False
        if detected_turn == 3 and not has_thonar_card:
            return (
                DogsFloor4Phase3State.STALL_FOR_GAUGE,
                "talent_escalin hint is gimmick (3), but no Thonar card was found",
                False,
            )
        if detected_turn == 3:
            return (
                DogsFloor4Phase3State.TRIGGER_GIMMICK_1,
                "talent_escalin visible on screen (phase 3 gimmick cue)",
                True,
            )
        if both_gauges_ready and gold_gauges_ready:
            return (
                DogsFloor4Phase3State.TRIGGER_GIMMICK_1,
                "both dogs are at >=3 ult gauge and 2 gold thonar_gauge cards are available",
                True,
            )
        if both_gauges_ready:
            return (
                DogsFloor4Phase3State.STALL_FOR_GAUGE,
                f"both dogs are ready, but only {len(gold_gauges)} gold thonar_gauge card(s) are available",
                False,
            )
        return (
            DogsFloor4Phase3State.STALL_FOR_GAUGE,
            "waiting for both dogs to reach >=3 ult gauge",
            False,
        )

    def _update_phase3_state(self, hand_of_cards: list[Card]):
        previous_state = DogsFloor4BattleStrategy.phase3_state
        new_state, reason, activate_trigger = self._phase3_transition_decision(hand_of_cards)
        if activate_trigger:
            self._phase3_activate_trigger_state()
        DogsFloor4BattleStrategy.phase3_state = new_state
        print(
            "Phase 3 sub-state update -> "
            f"{previous_state.value} -> {new_state.value}. Reason: {reason}. "
            f"Current gauges: {DogsFloor4BattleStrategy.phase3_dog_orbs}."
        )

    def _phase3_stall_action(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        if DogsFloor4BattleStrategy.turn == 0 and card_turn == 0:
            nasi_ult = self._best_matching_card(hand_of_cards, ("nasi_ult",))
            if nasi_ult != -1:
                print("Phase 3 stall: Turn 1 hard rule -> using nasi_ult first.")
                return nasi_ult

        if DogsFloor4BattleStrategy.turn == 0:
            low_value_card = self._phase3_low_value_play_action(hand_of_cards)
            if low_value_card != -1:
                print("Phase 3 stall: Turn 1 spending a low-value card to cycle the hand.")
                return low_value_card

        gauge_balance_action = self._phase3_stall_gauge_balance_action(hand_of_cards)
        if gauge_balance_action != -1:
            return gauge_balance_action

        if (
            DogsFloor4BattleStrategy.phase3_dog_orbs["left"] >= 3
            and DogsFloor4BattleStrategy.phase3_dog_orbs["right"] >= 3
            and len(self._thonar_gauge_ids_with_ranks(hand_of_cards, {CardRanks.GOLD})) < 2
        ):
            move_action = self._move_card_once(hand_of_cards, ("thonar_gauge",))
            if move_action is not None:
                print(
                    "Phase 3 stall: gauges are ready but 2 gold thonar_gauge cards are not. Merging/repositioning gauge cards."
                )
                return move_action

        move_action = self._phase3_preserved_nasi_move_action(hand_of_cards)
        if move_action is not None:
            print("Phase 3 stall: moving a preserved nasi card to rebuild toward nasi_ult again.")
            return move_action

        low_value_card = self._phase3_low_value_play_action(hand_of_cards)
        if low_value_card != -1:
            print("Phase 3 stall: using a low-value card to rebuild and cycle draws.")
            return low_value_card

        for template_names in [NASI_NON_ULT_TEMPLATES, ("thonar_stance",)]:
            merge_action = self._find_merge_move(hand_of_cards, template_names)
            if merge_action is not None:
                print(f"Phase 3 stall: using merge action for setup with {template_names}.")
                return merge_action

        move_action = self._move_card_once(hand_of_cards, ("thonar_gauge",))
        if move_action is not None:
            print("Phase 3 stall: moving thonar_gauge as a last-resort setup action.")
            return move_action

        for template_names in [
            NASI_TEMPLATES,
            ("thonar_stance",),
            ("escalin_st",),
            ("escalin_aoe",),
            ("roxy_st",),
            ("roxy_aoe",),
            ("escalin_ult",),
            ("roxy_ult",),
            ("thonar_ult",),
        ]:
            move_action = self._move_card_once(hand_of_cards, template_names)
            if move_action is not None:
                print(f"Phase 3 stall: using a reposition move with {template_names} instead of spending damage.")
                return move_action

        print("Phase 3 stall: no safe setup move was found, falling back to any non-gauge card.")
        return self._phase3_any_non_gauge_card(hand_of_cards)

    def _phase3_low_value_play_action(self, hand_of_cards: list[Card]) -> int:
        nasi_ult = self._best_matching_card(hand_of_cards, ("nasi_ult",))
        if nasi_ult != -1:
            return nasi_ult

        thonar_stance = self._best_matching_card(hand_of_cards, ("thonar_stance",))
        if thonar_stance != -1:
            return thonar_stance

        nasi_ids = self._matching_card_ids(hand_of_cards, NASI_NON_ULT_TEMPLATES)
        if len(nasi_ids) > 1:
            preserved_nasi_id = nasi_ids[-1]
            expendable_nasi_ids = [idx for idx in nasi_ids if idx != preserved_nasi_id]
            if expendable_nasi_ids:
                return self._lowest_rank_rightmost_card_id(hand_of_cards, expendable_nasi_ids)
        return -1

    def _phase3_preserved_nasi_move_action(self, hand_of_cards: list[Card]) -> list[int] | None:
        nasi_ids = self._matching_card_ids(hand_of_cards, NASI_NON_ULT_TEMPLATES)
        if not nasi_ids:
            return None

        preserved_nasi_id = nasi_ids[-1]
        target_idx = preserved_nasi_id + 1 if preserved_nasi_id < len(hand_of_cards) - 1 else preserved_nasi_id - 1
        if target_idx < 0 or target_idx == preserved_nasi_id:
            return None

        return [preserved_nasi_id, target_idx]

    def _phase3_stall_gauge_balance_action(self, hand_of_cards: list[Card]) -> int:
        gauges = DogsFloor4BattleStrategy.phase3_dog_orbs
        gauge_delta = abs(gauges["left"] - gauges["right"])
        if gauge_delta < PHASE3_GAUGE_DISPARITY_THRESHOLD:
            return -1

        gold_gauge_ids = self._thonar_gauge_ids_with_ranks(hand_of_cards, {CardRanks.GOLD})
        if len(gold_gauge_ids) < 2:
            return -1

        expendable_non_gold_gauges = self._phase3_expendable_non_gold_thonar_gauge_ids(hand_of_cards)
        if not expendable_non_gold_gauges:
            return -1

        if DogsFloor4BattleStrategy.turn == 1:
            target_side = "right"
        else:
            target_side = "left" if gauges["left"] > gauges["right"] else "right"
        chosen_idx = self._lowest_rank_rightmost_card_id(hand_of_cards, expendable_non_gold_gauges)
        DogsFloor4BattleStrategy.phase3_next_target_side = target_side
        print(
            "Phase 3 stall: using an expendable non-gold thonar_gauge to reduce ult-gauge disparity -> "
            f"target={target_side}, gauges={gauges}"
        )
        return chosen_idx

    def _phase3_expendable_non_gold_thonar_gauge_ids(self, hand_of_cards: list[Card]) -> list[int]:
        gauge_ids = self._thonar_gauge_ids(hand_of_cards)
        non_gold_gauge_ids = [idx for idx in gauge_ids if hand_of_cards[idx].card_rank != CardRanks.GOLD]
        if len(self._thonar_gauge_ids_with_ranks(hand_of_cards, {CardRanks.GOLD})) < 2:
            return []
        return non_gold_gauge_ids

    def _phase3_thonar_gauge_reduction(self, card: Card) -> int:
        if card.card_rank == CardRanks.GOLD:
            return 3
        if card.card_rank in {CardRanks.BRONZE, CardRanks.SILVER}:
            return 1
        return 0

    def _apply_phase3_gauge_reduction(self, target_side: str, reduction: int):
        if reduction <= 0:
            return

        DogsFloor4BattleStrategy.phase3_dog_orbs[target_side] = max(
            0,
            DogsFloor4BattleStrategy.phase3_dog_orbs[target_side] - reduction,
        )
        print(
            "Phase 3 gauge update after thonar_gauge -> "
            f"target={target_side}, reduction={reduction}, "
            f"orbs={DogsFloor4BattleStrategy.phase3_dog_orbs}"
        )

    def _phase3_gimmick_action(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        """Canonical gimmick line: Escalin talent then (optional nasi) -> gold right -> gold left -> escalin ult; extra slots use damage planner."""
        step = DogsFloor4BattleStrategy.phase3_gimmick_step
        nasi_ult_idx = self._best_matching_card(hand_of_cards, ("nasi_ult",))
        escalin_ult_idx = self._best_matching_card(hand_of_cards, ("escalin_ult",))

        if step == Phase3GimmickStep.OPENING_AFTER_TALENT:
            DogsFloor4BattleStrategy.phase3_use_talent_before_next_play = True
            print("Phase 3 gimmick: activating Escalin talent before the next card (playbook opener).")
            if nasi_ult_idx != -1:
                print("Phase 3 gimmick: opening with nasi_ult after talent when still in hand.")
                return nasi_ult_idx
            picked = self._phase3_pick_trigger_gauge_action(
                hand_of_cards,
                target_side="right",
                step_label="Phase 3 gimmick first gold-gauge (no nasi_ult in hand)",
            )
            if picked == -1:
                print(
                    "Phase 3 gimmick fallback: no nasi_ult and no gold thonar_gauge for right; "
                    "cannot start canonical sequence this read."
                )
            return picked

        if step == Phase3GimmickStep.GOLD_RIGHT:
            print("Phase 3 gimmick FSM step GOLD_RIGHT -> gold thonar_gauge on right dog.")
            return self._phase3_pick_trigger_gauge_action(
                hand_of_cards,
                target_side="right",
                step_label="Phase 3 gimmick gold-gauge right",
            )

        if step == Phase3GimmickStep.GOLD_LEFT:
            print("Phase 3 gimmick FSM step GOLD_LEFT -> gold thonar_gauge on left dog.")
            return self._phase3_pick_trigger_gauge_action(
                hand_of_cards,
                target_side="left",
                step_label="Phase 3 gimmick gold-gauge left",
            )

        if step == Phase3GimmickStep.ESCALIN_ULT:
            if escalin_ult_idx != -1:
                print("Phase 3 gimmick FSM step ESCALIN_ULT -> playing escalin_ult.")
                return escalin_ult_idx
            return self._phase3_heavy_fallback_pick(hand_of_cards, picked_cards, card_turn)

        if step == Phase3GimmickStep.COMPLETE:
            return self._phase3_heavy_fallback_pick(hand_of_cards, picked_cards, card_turn)

        return -1

    def _phase3_advance_gimmick_step_after_play(self, card: Card, target_side: str | None):
        """Single place to advance Phase3GimmickStep after a confirmed gimmick-turn play."""
        if not DogsFloor4BattleStrategy.phase3_trigger_turn_active:
            return
        step = DogsFloor4BattleStrategy.phase3_gimmick_step
        if self._card_matches_any(card, ("nasi_ult",)):
            if step == Phase3GimmickStep.OPENING_AFTER_TALENT:
                DogsFloor4BattleStrategy.phase3_gimmick_step = Phase3GimmickStep.GOLD_RIGHT
                print("Phase 3 gimmick FSM: nasi_ult opener -> GOLD_RIGHT.")
            return
        if (
            self._card_matches_any(card, ("thonar_gauge",))
            and card.card_rank == CardRanks.GOLD
            and target_side
            in (
                "left",
                "right",
            )
        ):
            if step == Phase3GimmickStep.OPENING_AFTER_TALENT and target_side == "right":
                DogsFloor4BattleStrategy.phase3_gimmick_step = Phase3GimmickStep.GOLD_LEFT
                print("Phase 3 gimmick FSM: gold gauge right (opening) -> GOLD_LEFT.")
            elif step == Phase3GimmickStep.GOLD_RIGHT and target_side == "right":
                DogsFloor4BattleStrategy.phase3_gimmick_step = Phase3GimmickStep.GOLD_LEFT
                print("Phase 3 gimmick FSM: gold gauge right -> GOLD_LEFT.")
            elif step == Phase3GimmickStep.GOLD_LEFT and target_side == "left":
                DogsFloor4BattleStrategy.phase3_gimmick_step = Phase3GimmickStep.ESCALIN_ULT
                print("Phase 3 gimmick FSM: gold gauge left -> ESCALIN_ULT.")
            return
        if step == Phase3GimmickStep.ESCALIN_ULT and self._card_matches_any(
            card,
            (
                "escalin_ult",
                "escalin_aoe",
                "escalin_st",
                "roxy_aoe",
                "roxy_st",
                "roxy_ult",
                "thonar_ult",
            ),
        ):
            DogsFloor4BattleStrategy.phase3_gimmick_step = Phase3GimmickStep.COMPLETE
            print("Phase 3 gimmick FSM: heavy damage card played after gold gauges -> COMPLETE.")

    def _phase3_pick_trigger_gauge_action(self, hand_of_cards: list[Card], target_side: str, step_label: str) -> int:
        gold_gauge_ids = self._thonar_gauge_ids_with_ranks(hand_of_cards, {CardRanks.GOLD})
        if gold_gauge_ids:
            DogsFloor4BattleStrategy.phase3_next_target_side = target_side
            return gold_gauge_ids[-1]

        print(
            f"{step_label}: expected a remaining trigger thonar_gauge for the {target_side} dog, "
            "but no gold thonar_gauge was detected on this reread."
        )
        return -1

    def _phase3_kill_action(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int):
        _ = card_turn
        esca_ult = self._best_matching_card(hand_of_cards, ("escalin_ult",))
        if esca_ult != -1:
            return esca_ult
        esca_aoe = self._best_matching_card(hand_of_cards, ("escalin_aoe",))
        if esca_aoe != -1:
            return esca_aoe
        st_idx = self._best_matching_card(hand_of_cards, ("escalin_st",))
        if st_idx != -1:
            DogsFloor4BattleStrategy.phase3_next_target_side = DogsFloor4BattleStrategy.phase3_kill_next_st_side
            return st_idx
        print("Phase 3 kill: no Escalin card; delegating to SmarterBattleStrategy.")
        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def _phase3_heavy_fallback_pick(self, hand_of_cards: list[Card], picked_cards: list[Card], card_turn: int) -> int:
        _ = card_turn
        for templates in (
            ("escalin_ult",),
            ("escalin_aoe",),
            ("escalin_st",),
            ("roxy_aoe",),
            ("roxy_st",),
            ("roxy_ult",),
            ("thonar_ult",),
        ):
            idx = self._best_matching_card(hand_of_cards, templates)
            if idx == -1:
                continue
            if templates == ("escalin_st",):
                DogsFloor4BattleStrategy.phase3_next_target_side = DogsFloor4BattleStrategy.phase3_kill_next_st_side
            return idx
        print("Phase 3 heavy fallback: delegating to SmarterBattleStrategy.")
        return SmarterBattleStrategy.get_next_card_index(hand_of_cards, picked_cards)

    def _phase3_any_non_gauge_card(self, hand_of_cards: list[Card]) -> int:
        preserved_nasi_ids = set()
        nasi_ids = self._matching_card_ids(hand_of_cards, NASI_NON_ULT_TEMPLATES)
        if nasi_ids:
            preserved_nasi_ids.add(nasi_ids[-1])

        for idx, card in reversed(list(enumerate(hand_of_cards))):
            if card.card_type in (CardTypes.DISABLED, CardTypes.NONE, CardTypes.GROUND):
                continue
            if idx in preserved_nasi_ids:
                continue
            if self._card_matches_any(card, ("thonar_gauge",)):
                continue
            return idx
        return -1

    def _best_matching_card(self, hand_of_cards: list[Card], template_names: Sequence[str]) -> int:
        matching_ids = self._matching_card_ids(hand_of_cards, template_names)
        return matching_ids[-1] if matching_ids else -1

    def _best_matching_card_with_ranks(
        self, hand_of_cards: list[Card], template_names: Sequence[str], ranks: set[CardRanks]
    ) -> int:
        matching_ids = [
            idx
            for idx in self._matching_card_ids(hand_of_cards, template_names)
            if hand_of_cards[idx].card_rank in ranks
        ]
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

    def _card_template_name(self, card: Card, template_names: Sequence[str]) -> str | None:
        return next(
            (template_name for template_name in template_names if self._card_matches_any(card, (template_name,))),
            None,
        )

    def estimate_auto_merge_count_after_play(self, hand_of_cards: list[Card], played_idx: int) -> int:
        if not (0 <= played_idx < len(hand_of_cards)):
            return 0

        simulated_cards = []
        for idx, card in enumerate(hand_of_cards):
            if idx == played_idx:
                continue
            template_name = self._card_template_name(
                card,
                ESCALIN_TEMPLATES + ROXY_TEMPLATES + NASI_TEMPLATES + THONAR_TEMPLATES,
            )
            simulated_cards.append(
                {
                    "template_name": template_name,
                    "card_rank": card.card_rank,
                }
            )

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
                simulated_cards[cursor] = {
                    "template_name": left_card["template_name"],
                    "card_rank": next_rank,
                }
                del simulated_cards[cursor + 1]
                merge_count += 1
                cursor = max(0, cursor - 1)
                continue
            cursor += 1

        return merge_count

    def _phase2_move_action(self, hand_of_cards: list[Card]) -> list[int] | None:
        for template_names in [
            NASI_NON_ULT_TEMPLATES,
            ("escalin_st", "escalin_aoe"),
            ROXY_NON_ULT_TEMPLATES,
            ("thonar_stance",),
        ]:
            move_action = self._move_card_once(hand_of_cards, template_names)
            if move_action is not None:
                return move_action
        return None

    def _phase2_last_resort_move_action(self, hand_of_cards: list[Card]) -> list[int] | None:
        for template_names in [
            NASI_TEMPLATES,
            ("thonar_stance",),
            ("escalin_st", "escalin_aoe", "escalin_ult"),
            ROXY_TEMPLATES,
            ("thonar_ult",),
            ("thonar_gauge",),
        ]:
            move_action = self._move_card_once(hand_of_cards, template_names)
            if move_action is not None:
                return move_action
        return None

    def _phase2_nasi_ult_unlock_action(self, hand_of_cards: list[Card]) -> int:
        nasi_ult = self._best_matching_card(hand_of_cards, ("nasi_ult",))
        if nasi_ult == -1:
            return -1
        if self._best_matching_card(hand_of_cards, ("nasi_heal",)) != -1:
            return -1

        for template_names in [
            ("escalin_st",),
            ROXY_NON_ULT_TEMPLATES,
            ("escalin_aoe",),
            ("thonar_stance",),
            ("nasi_stun",),
        ]:
            if self._best_allowed_card(hand_of_cards, template_names) != -1:
                return -1

        if self._phase2_move_action(hand_of_cards) is not None:
            return -1

        return nasi_ult

    def _phase2_any_visible_card(self, hand_of_cards: list[Card], allow_protected_gauges=False) -> int:
        visible_ids = []
        for idx, card in enumerate(hand_of_cards):
            if card.card_type in (CardTypes.DISABLED, CardTypes.NONE, CardTypes.GROUND):
                continue
            if self._card_matches_any(card, ("nasi_ult",)):
                continue
            if not allow_protected_gauges and idx in self._protected_thonar_gauge_ids(hand_of_cards):
                continue
            visible_ids.append(idx)
        return visible_ids[-1] if visible_ids else -1

    def _move_card_once(self, hand_of_cards: list[Card], template_names: Sequence[str]) -> list[int] | None:
        if merge_move := self._find_merge_move(hand_of_cards, template_names):
            return merge_move

        matching_ids = self._matching_card_ids(hand_of_cards, template_names)
        if not matching_ids:
            return None

        origin_idx = matching_ids[-1]
        target_idx = origin_idx + 1 if origin_idx < len(hand_of_cards) - 1 else origin_idx - 1
        if target_idx < 0 or target_idx == origin_idx:
            return None

        return [origin_idx, target_idx]

    def _find_merge_move(self, hand_of_cards: list[Card], template_names: Sequence[str]) -> list[int] | None:
        groups: dict[tuple[str, CardRanks], list[int]] = {}
        for idx in self._matching_card_ids(hand_of_cards, template_names):
            card = hand_of_cards[idx]
            if card.card_rank not in {CardRanks.BRONZE, CardRanks.SILVER}:
                continue

            template_name = self._card_template_name(card, template_names)
            if template_name is None:
                continue

            key = (template_name, card.card_rank)
            groups.setdefault(key, []).append(idx)

        for (_, _), ids in sorted(groups.items(), key=lambda item: item[0][1].value, reverse=True):
            if len(ids) >= 2:
                return [ids[0], ids[1]]

        return None

    def _played_count(self, picked_cards: list[Card], template_names: Sequence[str]) -> int:
        return sum(self._card_matches_any(card, template_names) for card in picked_cards if card.card_image is not None)

    def _has_card_in_hand_or_picked(
        self, hand_of_cards: list[Card], picked_cards: list[Card], template_names: Sequence[str]
    ) -> bool:
        return any(
            self._card_matches_any(card, template_names) for card in hand_of_cards if card.card_image is not None
        ) or any(self._card_matches_any(card, template_names) for card in picked_cards if card.card_image is not None)

    def _thonar_gauge_ids(self, hand_of_cards: list[Card]) -> list[int]:
        return self._matching_card_ids(hand_of_cards, ("thonar_gauge",))

    def _thonar_gauge_ids_with_ranks(self, hand_of_cards: list[Card], ranks: set[CardRanks]) -> list[int]:
        return [idx for idx in self._thonar_gauge_ids(hand_of_cards) if hand_of_cards[idx].card_rank in ranks]

    def _protected_thonar_gauge_ids(self, hand_of_cards: list[Card]) -> set[int]:
        gauge_ids = self._thonar_gauge_ids(hand_of_cards)
        if len(gauge_ids) <= 2:
            return set(gauge_ids)
        return set(gauge_ids[-2:])

    def _expendable_thonar_gauge_ids(self, hand_of_cards: list[Card]) -> list[int]:
        protected_ids = self._protected_thonar_gauge_ids(hand_of_cards)
        return [idx for idx in self._thonar_gauge_ids(hand_of_cards) if idx not in protected_ids]

    def _lowest_expendable_thonar_gauge_id(self, hand_of_cards: list[Card]) -> int:
        expendable_ids = self._expendable_thonar_gauge_ids(hand_of_cards)
        if not expendable_ids:
            return -1
        return self._lowest_rank_rightmost_card_id(hand_of_cards, expendable_ids)

    def _is_forbidden_phase2_card(self, hand_of_cards: list[Card], idx: int) -> bool:
        card = hand_of_cards[idx]
        if self._card_matches_any(card, ("nasi_ult",)):
            return True
        if idx in self._protected_thonar_gauge_ids(hand_of_cards):
            return True
        return False

    def _best_allowed_card(self, hand_of_cards: list[Card], template_names: Sequence[str]) -> int:
        matching_ids = self._matching_card_ids(hand_of_cards, template_names)
        allowed_ids = [idx for idx in matching_ids if not self._is_forbidden_phase2_card(hand_of_cards, idx)]
        return allowed_ids[-1] if allowed_ids else -1

    def _phase2_any_allowed_card(self, hand_of_cards: list[Card]) -> int:
        allowed_ids = [
            idx
            for idx, card in enumerate(hand_of_cards)
            if card.card_type not in (CardTypes.DISABLED, CardTypes.NONE, CardTypes.GROUND)
            and not self._is_forbidden_phase2_card(hand_of_cards, idx)
        ]
        return allowed_ids[-1] if allowed_ids else -1

    def should_finish_phase2_turn_early(self, _hand_of_cards: list[Card]) -> bool:
        return False

    def register_confirmed_action(self, hand_of_cards: list[Card], action, played_card: Card | None = None):
        if isinstance(action, int):
            if played_card is None or played_card.card_image is None:
                return
            if unit_name := self._unit_name_from_card(played_card):
                self._register_play_action(unit_name, played_card)
        elif isinstance(action, (list, tuple)) and len(action) == 2:
            origin_idx, target_idx = action
            if 0 <= origin_idx < len(hand_of_cards) and 0 <= target_idx < len(hand_of_cards):
                if unit_name := self._unit_name_from_card(hand_of_cards[origin_idx]):
                    merged = self._move_creates_merge(hand_of_cards, origin_idx, target_idx)
                    self._register_move_action(unit_name, merged=merged)

    def _register_and_return_action(self, hand_of_cards: list[Card], action):
        if isinstance(action, int):
            if 0 <= action < len(hand_of_cards):
                if unit_name := self._unit_name_from_card(hand_of_cards[action]):
                    self._register_play_action(unit_name, hand_of_cards[action])
        elif isinstance(action, (list, tuple)) and len(action) == 2:
            origin_idx, target_idx = action
            if 0 <= origin_idx < len(hand_of_cards) and 0 <= target_idx < len(hand_of_cards):
                if unit_name := self._unit_name_from_card(hand_of_cards[origin_idx]):
                    merged = self._move_creates_merge(hand_of_cards, origin_idx, target_idx)
                    self._register_move_action(unit_name, merged=merged)
        return action

    def _unit_name_from_card(self, card: Card) -> str | None:
        if self._card_matches_any(card, ESCALIN_TEMPLATES):
            return "escalin"
        if self._card_matches_any(card, ROXY_TEMPLATES):
            return "roxy"
        if self._card_matches_any(card, NASI_TEMPLATES):
            return "nasi"
        if self._card_matches_any(card, THONAR_TEMPLATES):
            return "thonar"
        return None

    def _move_creates_merge(self, hand_of_cards: list[Card], origin_idx: int, target_idx: int) -> bool:
        origin_card = hand_of_cards[origin_idx]
        target_card = hand_of_cards[target_idx]
        origin_unit = self._unit_name_from_card(origin_card)
        target_unit = self._unit_name_from_card(target_card)
        if origin_unit is None or origin_unit != target_unit:
            return False
        if origin_card.card_rank != target_card.card_rank:
            return False
        return origin_card.card_rank in {CardRanks.BRONZE, CardRanks.SILVER}

    def _register_play_action(self, _unit_name: str, _card: Card):
        pass

    def _register_move_action(self, _unit_name: str, merged=False):
        pass

    def register_phase3_card_play(self, card: Card, target_side: str | None = None):
        if DogsFloor4BattleStrategy._last_phase_seen != 3 or card.card_image is None:
            return

        if DogsFloor4BattleStrategy.phase3_trigger_turn_active:
            self._phase3_advance_gimmick_step_after_play(card, target_side)

        if self._card_matches_any(card, ("thonar_gauge",)) and target_side in {"left", "right"}:
            reduction = self._phase3_thonar_gauge_reduction(card)
            self._apply_phase3_gauge_reduction(target_side, reduction)
            DogsFloor4BattleStrategy.phase3_trigger_gauge_targets_used.add(target_side)
            print(
                "Phase 3 trigger tracking: used thonar_gauge on "
                f"{target_side} dog (rank={card.card_rank.name}, reduction={reduction})."
            )
            return

        if self._card_matches_any(card, ("escalin_st",)) and not DogsFloor4BattleStrategy.phase3_trigger_turn_active:
            side = DogsFloor4BattleStrategy.phase3_kill_next_st_side
            DogsFloor4BattleStrategy.phase3_kill_next_st_side = "right" if side == "left" else "left"

    def register_phase3_talent_use(self):
        if DogsFloor4BattleStrategy._last_phase_seen != 3:
            return
        print("Phase 3: Escalin talent used (HP simulator removed; no damage bookkeeping).")
