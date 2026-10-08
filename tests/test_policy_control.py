from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from alladin.agents.mock import MockAgent
from alladin.api.app import create_app
from alladin.brain import Action, ActionProposal, ProposalParameters, proposal_identity
from alladin.challenge.event_policy import CalendarSnapshot, EconomicEvent
from alladin.challenge.firm_policy import FirmProfile
from alladin.challenge.policy_gate import GateVerdict, PolicyContext
from alladin.core.enums import RunMode
from alladin.core.errors import AlladinError
from alladin.orchestration.policy_control import PolicyController, policy_journal_report
from tests.test_position_lifecycle import SequenceBrain, action, opened


def context(svc, proposal, *, missing=False, restricted=False):
    now = proposal.timestamp
    profile = FirmProfile(firm='synthetic',program='fixture',phase='funded',account_type='test',version='1',
                          source_url='https://example.test/synthetic',verified_at=now-timedelta(days=1),
                          valid_until=now+timedelta(days=1),allowed_symbols=frozenset({proposal.symbol}),ea_allowed=True,
                          restrict_news=restricted)
    cal = CalendarSnapshot(now, now+timedelta(hours=1),'synthetic',
                           (EconomicEvent('CPI',now,frozenset({'EURUSD'}),True),) if restricted else ())
    return PolicyContext(now,proposal.symbol,0,profile,None if missing else cal,restricted)


def controller(svc, **kwargs):
    assert svc.run.account_binding is not None
    return PolicyController(binding=svc.run.account_binding,journal=svc.journal,
                            context_provider=lambda p: context(svc,p,**kwargs))


def proposal(svc, kind):
    params = (ProposalParameters(strategy_id='TREND-01',strategy_version='1.0.0',
                                 requested_risk_pct_of_working_capital=4.) if kind is Action.LONG
              else ProposalParameters(position_id='P-1',stop_loss=1.084 if kind is Action.MODIFY_STOP else None,
                                      take_profit=1.089 if kind is Action.MODIFY_TARGET else None,
                                      partial_fraction=.5 if kind is Action.PARTIAL_CLOSE else None))
    return ActionProposal(proposal_id=proposal_identity(svc.run.run_id,'C-1','OPP-1','test','1'),source_id='test',
                          source_version='1',run_id=svc.run.run_id,cycle_id='C-1',opportunity_id='OPP-1',
                          symbol='EURUSD',action=kind,timestamp=svc.broker.now(),parameters=params)


@pytest.mark.parametrize('kind',[Action.LONG,Action.CLOSE,Action.PARTIAL_CLOSE,Action.MODIFY_STOP,Action.MODIFY_TARGET,Action.HOLD])
@pytest.mark.parametrize('mode',[RunMode.OBSERVE,RunMode.PAPER])
def test_all_actions_journalled_without_order_send(svc,monkeypatch,kind,mode):
    monkeypatch.setattr(svc.broker,'_send',lambda *a,**kw: pytest.fail('unexpected broker execution'))
    c = controller(svc)
    p = proposal(svc,kind)
    assert c.assess(p,mode).verdict is GateVerdict.ALLOW
    assert c.assess(p,mode).verdict is GateVerdict.ALLOW
    report = policy_journal_report(svc.journal,svc.run.run_id)
    assert report['decisions'] == 1
    assert report['journal_integrity']['ok']
    assert report['execution_authorized'] is False
    assert report['wall_clock_availability'] is None
    restored = controller(svc)
    assert restored.assess(p,mode).verdict is GateVerdict.ALLOW
    assert len(svc.repo.events(svc.run.run_id,types=['policy.decision'])) == 1


@pytest.mark.parametrize('kind',[Action.LONG,Action.CLOSE,Action.PARTIAL_CLOSE,Action.MODIFY_STOP,Action.MODIFY_TARGET])
def test_outage_and_replay_mismatch(svc,kind):
    p=proposal(svc,kind)
    c=controller(svc,missing=True)
    verdict = GateVerdict.BLOCK if kind is Action.LONG else GateVerdict.REVIEW
    assert c.assess(p,RunMode.PAPER).verdict is verdict
    assert policy_journal_report(svc.journal,svc.run.run_id)['data_available_fraction'] == 0
    result=controller(svc).assess(p,RunMode.PAPER)
    assert result.reason == 'POLICY_REPLAY_MISMATCH' and result.verdict is verdict
    assert len(policy_journal_report(svc.journal,svc.run.run_id)['incidents']) == 1


@pytest.mark.parametrize('kind',[Action.HOLD,Action.MODIFY_STOP,Action.CLOSE])
@pytest.mark.parametrize('blocked',[False,True])
def test_paper_orchestration_management_checkpoint(svc,monkeypatch,kind,blocked):
    monkeypatch.setattr(svc.broker,'_send',lambda *a,**kw: pytest.fail('unexpected broker execution'))
    paper=opened(svc,RunMode.PAPER)
    engine=svc.engine(MockAgent(),brain=SequenceBrain(kind),run_mode=RunMode.PAPER,
                      policy_controller=controller(svc,restricted=blocked))
    engine.paper_engine=paper
    result=engine.run_cycle()
    assert result.decision == ('NO_TRADE' if blocked and kind is not Action.HOLD else kind.value)
    assert policy_journal_report(svc.journal,svc.run.run_id)['decisions'] == 1


def test_mode_and_binding_rejected(svc):
    c=controller(svc)
    with pytest.raises(ValueError):
        c.assess(proposal(svc,Action.LONG),RunMode.DEMO)
    with pytest.raises(AlladinError):
        svc.engine(MockAgent(),run_mode=RunMode.DEMO,policy_controller=c)
    c.binding=c.binding.model_copy(update={'account_ref':'different'})
    with pytest.raises(AlladinError):
        svc.engine(MockAgent(),policy_controller=c)
    with pytest.raises(ValueError):
        c.assess(proposal(svc,Action.LONG),RunMode.PAPER)


def test_provider_fault_sanitized_and_identity_mismatch(svc):
    c=controller(svc)
    p=proposal(svc,Action.LONG)
    c.context_provider=lambda p: replace(context(svc,p),now=p.timestamp+timedelta(seconds=1))
    assert c.assess(p,RunMode.PAPER).reason == 'POLICY_CONTEXT_UNAVAILABLE'
    report=policy_journal_report(svc.journal,svc.run.run_id)
    assert report['latest']['provider_error'] == 'ValueError'
    assert report['data_unavailable_decisions'] == 1


def test_policy_api_empty_and_evidence(svc):
    api=TestClient(create_app(svc.settings,svc.repo,None))
    assert api.get('/api/policy').json()['data_available_fraction'] is None
    controller(svc).assess(proposal(svc,Action.LONG),RunMode.OBSERVE)
    report=api.get('/api/policy').json()
    assert report['decisions'] == 1 and report['unattended_qualified'] is False
    assert api.get('/api/policy?run_id=absent').status_code == 404


@pytest.mark.parametrize('kind',[Action.PARTIAL_CLOSE,Action.MODIFY_TARGET])
def test_paper_remaining_management_actions(svc,monkeypatch,kind):
    from alladin.brain import BrainContext

    class ManagementBrain:
        source_id, source_version = 'test', '1'

        def decide(self, ctx: BrainContext):
            return action(svc,RunMode.PAPER,kind,paper,cycle=ctx.cycle_id)

    monkeypatch.setattr(svc.broker,'_send',lambda *a,**kw: pytest.fail('unexpected broker execution'))
    paper=opened(svc,RunMode.PAPER)
    engine=svc.engine(MockAgent(),brain=ManagementBrain(),run_mode=RunMode.PAPER,policy_controller=controller(svc))
    engine.paper_engine=paper
    outcome=engine.run_cycle()
    assert outcome.decision == kind.value, outcome.reason


@pytest.mark.parametrize('missing',[False,True])
def test_paper_entry_keeps_risk_validation(svc,monkeypatch,missing):
    from alladin.brain import BrainContext

    class EntryBrain:
        source_id, source_version = 'test','1'

        def decide(self, ctx: BrainContext):
            symbol,opportunity=next(iter(ctx.opportunities.items()))
            p=proposal(svc,Action.LONG)
            return p.model_copy(update={'symbol':symbol,'cycle_id':ctx.cycle_id,'opportunity_id':opportunity,
                'proposal_id':proposal_identity(ctx.run_id,ctx.cycle_id,opportunity,'test','1')})

    monkeypatch.setattr(svc.broker,'_send',lambda *a,**kw: pytest.fail('unexpected broker execution'))
    engine=svc.engine(MockAgent(),brain=EntryBrain(),run_mode=RunMode.PAPER,policy_controller=controller(svc,missing=missing))
    outcome=engine.run_cycle()
    report=policy_journal_report(svc.journal,svc.run.run_id)
    assert report['decisions'] == 1, outcome
    if missing:
        assert outcome.decision == 'NO_TRADE' and 'CALENDAR_MISSING' in outcome.reason
        assert engine.paper_engine.open_positions() == () or not engine.paper_engine.open_positions()
    else:
        assert report['latest']['verdict'] == 'ALLOW'
        assert svc.repo.events(svc.run.run_id,types=['risk.decision'])
