"""OBSERVE-only Jafar skeleton. No trading strategy is inherited."""
from alladin.brain import Action, ActionProposal, BrainContext, proposal_identity


class JafarObserveBrain:
    source_id = "jafar:observe"
    source_version = "1"

    def decide(self, context: BrainContext) -> ActionProposal:
        return ActionProposal(
            proposal_id=proposal_identity(context.run_id, context.cycle_id, None,
                                          self.source_id, self.source_version),
            run_id=context.run_id, cycle_id=context.cycle_id, source_id=self.source_id,
            source_version=self.source_version, timestamp=context.timestamp,
            action=Action.NO_TRADE, reasons=("Jafar skeleton: OBSERVE only, no strategy enabled",),
        )
