"""Freeze eligible company context; retrieval never promotes candidate knowledge."""
import re
from pitr.domain.common import digest
from .contracts import NewsProfile


def profiles(station, selected=()):
    from pitr.domain.contracts import Scope
    result = []
    for identity in station.store.list('subject'):
        company = identity.id
        if selected and company not in selected: continue
        items = []
        for value in station.knowledge(Scope(subjects=[company])):
            if value['current_validity']['status'] != 'available': continue
            kind = 'relation' if value.get('kind') == 'relationship' else 'model' if 'assumptions' in value else 'knowledge'
            items.append({'ref': f"{value['id']}@{value['revision']}", 'kind': kind, 'title': value['title'],
                'text': value.get('statement', value.get('rationale', '')),
                'href': '/companies/'+company+'/knowledge?object='+value['id']+'&revision='+str(value['revision'])})
        body = dict(company=company, name=identity.name, aliases=sorted({company, identity.name, *identity.aliases}),
            identity_version=identity.ref.key, items=sorted(items,key=lambda item:item['ref']))
        result.append(NewsProfile(id='profile_'+digest(body)[:24], **body))
    return result


def alias_matches(text, aliases):
    return [a for a in aliases if (re.search(r'(?<![\w])'+re.escape(a)+r'(?![\w])', text, re.I)
                                  if a.isascii() else a.casefold() in text.casefold())]


def passages(text, width=700):
    """Overlapping passages include the end of long articles and company pages."""
    return [{'text': text[i:i+width], 'start': i, 'end': min(len(text), i+width)}
            for i in range(0, len(text), width-100)] or [{'text': '', 'start': 0, 'end': 0}]
