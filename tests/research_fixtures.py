"""Deterministic semantic results for offline tests of the research controller."""
from pitr.desk.research.intake import Intake
from pitr.desk.research.service import Research as ResearchService
from pitr.desk.research.contracts import ResearchInterpretation, ResearchSubject

class Research(ResearchService):
    def create(self,request):
        company=request.company or 'PDD'
        resolved=ResearchInterpretation(title='离线研究验收',intent=request.intent if request.intent!='auto' else 'investigation',
            subjects=[ResearchSubject(company_id=company,name=company,verified=True)],period=request.period,
            questions=[],plan=['核对原始来源']).model_dump()
        return Intake(self.desk,self.queue).create(request,resolved=resolved)


def resolve_pending(desk, intent=None):
    from pitr.desk.research.intake import IntakeWorker
    def resolver(desk,request,messages,key,fence):
        value=dict(ResearchService(desk).get(request['id'])['interpretation'])
        value.update(clarification='',options=[])
        if intent:value['intent']=intent
        return value
    IntakeWorker(desk,resolver=resolver).run_one()
